"""Orchestrator — yengil dispatcher (LLM emas).

Bazadan tugamagan vazifalarni o'qiydi, Planner → Executor(parallel) → Reviewer agentlarni
chaqiradi, holatni bazaga qaytaradi. Process/server uzilsa, idempotent davom etadi
(`has_subtasks` tekshiruvi rejalashtirishni takrorlamaydi).

`run_agent` injektsiya qilinadi (test uchun mock; default — runner.run_agent).
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from .agents import AGENT_SPECS
from .db import AsyncDB
from .models import TERMINAL_STATUSES, Task, TaskStatus
from .reporter import TelegramReporter
from .runner import extract_json
from .secrets import SecretStore

# (role, prompt, *, model, session_id) -> (text, session_id)
RunAgentFn = Callable[..., Awaitable[tuple[str, "str | None"]]]


class Orchestrator:
    def __init__(
        self,
        db: AsyncDB,
        store: SecretStore,
        reporter: TelegramReporter,
        *,
        run_agent: RunAgentFn | None = None,
    ):
        self._db = db
        self._store = store
        self._reporter = reporter
        if run_agent is None:
            from .runner import run_agent as _ra

            run_agent = _ra
        self._run_agent = run_agent

    # ── Konfiguratsiya (dinamik) ─────────────────────────────────────────────
    async def _model(self, role: str) -> str:
        spec = AGENT_SPECS[role]
        return await self._store.get_config(spec.model_key, spec.default_model)

    async def _max_retry(self) -> int:
        return await self._store.get_int("MAX_RETRY", 2)

    async def _max_parallel(self) -> int:
        return max(1, await self._store.get_int("MAX_PARALLEL", 5))

    async def _poll_interval(self) -> float:
        return await self._store.get_float("POLL_INTERVAL", 2.0)

    # ── Agent chaqiruvi + agent_run audit + on_block ─────────────────────────
    async def _call_agent(self, role: str, task: Task, prompt: str) -> tuple[str, str | None]:
        model = await self._model(role)
        run = await self._db.start_agent_run(task.id, role, model)

        async def on_block(cmd: str, why: str) -> None:
            await self._reporter.warn(
                f"Xavfli komanda bloklandi ({role}): `{cmd}` [{why}]", task_id=task.id
            )

        try:
            text, session_id = await self._run_agent(
                role, prompt, model=model, session_id=task.session_id, on_block=on_block
            )
            await self._db.finish_agent_run(run.id, "done")
            return text, session_id
        except Exception as exc:  # noqa: BLE001
            await self._db.finish_agent_run(run.id, "error")
            await self._reporter.report(
                agent_id=run.id, role=role, task_id=task.id,
                status_text=f"🔴 xato: {exc}",
            )
            raise

    # ── Asosiy: bitta root vazifani boshqarish ───────────────────────────────
    async def handle_task(self, task: Task) -> None:
        # 1) Idempotent resume: allaqachon rejalashtirilgan bo'lsa — qayta rejalashtirmaymiz.
        if await self._db.has_subtasks(task.id):
            await self._resume_and_execute(task)
            return

        # 2) Planning.
        await self._db.update_status(task.id, TaskStatus.ANALYZING)
        await self._reporter.report(
            agent_id="planner", role="planner", task_id=task.id,
            status_text="🟡 tahlil boshlandi",
        )
        try:
            text, _ = await self._call_agent("planner", task, task.description or task.title)
            plan = extract_json(text)
        except Exception as exc:  # noqa: BLE001
            await self._db.update_status(task.id, TaskStatus.FAILED)
            await self._reporter.report(
                agent_id="planner", role="planner", task_id=task.id,
                status_text=f"🔴 reja tuzilmadi: {exc}",
            )
            return

        strategy = plan.get("strategy", "")
        subtasks = plan.get("subtasks", []) or []
        await self._db.set_strategy(task.id, strategy)
        await self._db.save_subtasks(task.id, subtasks)
        await self._db.update_status(task.id, TaskStatus.PLANNED)
        await self._reporter.report(
            agent_id="planner", role="planner", task_id=task.id,
            status_text=f"🟢 {len(subtasks)} ta subtask rejalashtirildi",
        )

        await self._resume_and_execute(task)

    # ── Subtask'larni deps bo'yicha parallel ijro etish ──────────────────────
    async def _resume_and_execute(self, task: Task) -> None:
        subtasks = await self._db.list_subtasks(task.id)
        ok = await self._execute_subtasks(subtasks)

        final = TaskStatus.DONE if ok else TaskStatus.FAILED
        await self._db.update_status(task.id, final)
        emoji = "✅" if ok else "🔴"
        await self._reporter.report(
            agent_id="orchestrator", role="orchestrator", task_id=task.id,
            status_text=f"{emoji} root vazifa {final.value}",
        )

    async def _execute_subtasks(self, subtasks: list[Task]) -> bool:
        sem = asyncio.Semaphore(await self._max_parallel())
        done_ids = {t.id for t in subtasks if t.status is TaskStatus.DONE}
        failed = {t.id for t in subtasks if t.status is TaskStatus.FAILED}
        pending = {t.id: t for t in subtasks if t.status not in TERMINAL_STATUSES}

        while pending:
            # deps bajarilgan (DONE) subtask'lar — tayyor.
            ready = [
                t for t in pending.values() if all(d in done_ids for d in t.deps)
            ]
            if not ready:
                break  # qolganlar fail bo'lgan deps tomonidan bloklangan → deadlock

            async def _run(st: Task) -> tuple[str, bool]:
                async with sem:
                    return st.id, await self._process_subtask(st)

            results = await asyncio.gather(*[_run(t) for t in ready])
            for sid, success in results:
                pending.pop(sid, None)
                (done_ids if success else failed).add(sid)

        # Barcha subtask DONE bo'lsa va hech biri pending/fail bo'lmasa — muvaffaqiyat.
        return not failed and not pending

    # ── Bitta subtask: executor → reviewer → retry ───────────────────────────
    async def _process_subtask(self, st: Task) -> bool:
        max_retry = await self._max_retry()
        while True:
            # Execute
            await self._db.update_status(st.id, TaskStatus.EXECUTING)
            await self._reporter.report(
                agent_id="executor", role="executor", task_id=st.id,
                status_text=f"🟡 bajarilmoqda: {st.title}",
            )
            try:
                exec_text, _ = await self._call_agent("executor", st, st.title)
            except Exception:  # noqa: BLE001
                outcome = await self._fail_or_retry(st, max_retry, "executor xatosi")
                if outcome is None:
                    continue  # retry
                return outcome  # False → FAILED
            await self._db.set_result(st.id, exec_text)

            # Review
            await self._db.update_status(st.id, TaskStatus.REVIEWING)
            await self._reporter.report(
                agent_id="reviewer", role="reviewer", task_id=st.id,
                status_text="🟡 tekshirilmoqda",
            )
            review_prompt = (
                f"Subtask: {st.title}\n\nExecutor natijasi:\n{exec_text}\n\n"
                "Ishni tekshir va testlarni ishga tushir. Faqat JSON qaytar."
            )
            try:
                review_text, _ = await self._call_agent("reviewer", st, review_prompt)
                verdict = extract_json(review_text)
            except Exception:  # noqa: BLE001
                outcome = await self._fail_or_retry(st, max_retry, "reviewer xatosi")
                if outcome is None:
                    continue  # retry
                return outcome  # False → FAILED

            if verdict.get("passed") is True:
                await self._db.update_status(st.id, TaskStatus.DONE)
                await self._reporter.report(
                    agent_id="reviewer", role="reviewer", task_id=st.id,
                    status_text="🟢 o'tdi → DONE",
                )
                return True

            # Fail → retry yoki FAILED
            report = verdict.get("report", "test o'tmadi")
            retry = await self._fail_or_retry(st, max_retry, report)
            if retry is not None:
                return retry  # FAILED bo'ldi
            # aks holda sikl boshiga qaytib qayta urinadi

    async def _fail_or_retry(
        self, st: Task, max_retry: int, report: str
    ) -> bool | None:
        """attempts++; agar limitdan oshsa FAILED (False qaytaradi), aks holda None
        (chaqiruvchi qayta urinadi)."""
        attempts = await self._db.increment_attempts(st.id)
        if attempts > max_retry:
            await self._db.update_status(st.id, TaskStatus.FAILED)
            await self._reporter.report(
                agent_id="reviewer", role="reviewer", task_id=st.id,
                status_text=f"🔴 {attempts-1} urinishdan keyin FAILED: {report}",
            )
            return False
        await self._reporter.report(
            agent_id="reviewer", role="reviewer", task_id=st.id,
            status_text=f"🟠 fail ({report}) — qayta urinish #{attempts}",
        )
        return None

    # ── Cheksiz sikl ─────────────────────────────────────────────────────────
    async def run_forever(self, *, stop_event: asyncio.Event | None = None) -> None:
        while stop_event is None or not stop_event.is_set():
            task = await self._db.next_pending_root()
            if task is not None:
                await self.handle_task(task)
            else:
                await asyncio.sleep(await self._poll_interval())

    async def run_once(self) -> bool:
        """Bitta navbatdagi vazifani qayta ishlaydi (test/CLI uchun). Bor bo'lsa True."""
        task = await self._db.next_pending_root()
        if task is None:
            return False
        await self.handle_task(task)
        return True
