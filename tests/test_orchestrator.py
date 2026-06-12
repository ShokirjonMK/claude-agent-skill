"""Orchestrator testlari: planner→executor(parallel)→reviewer→DONE, retry, fail, resume."""

from __future__ import annotations

import asyncio
import json

import pytest

from orchestra.models import Task, TaskStatus
from orchestra.orchestrator import Orchestrator
from orchestra.reporter import TelegramReporter


class FakeRunner:
    """Skriptlangan run_agent mock: rol bo'yicha javob qaytaradi, chaqiruvlarni sanaydi,
    executor parallelizmini o'lchaydi."""

    def __init__(self, planner_response, *, executor_text="bajarildi", reviewer_seq=None):
        self.planner_response = planner_response
        self.executor_text = executor_text
        # reviewer_seq: bool ro'yxati (tartib bo'yicha) yoki None → doim True
        self.reviewer_seq = list(reviewer_seq) if reviewer_seq is not None else None
        self.calls: list[str] = []
        self._concurrent = 0
        self.max_concurrent = 0

    async def __call__(self, role, prompt, *, model, session_id=None, on_block=None):
        self.calls.append(role)
        if role == "planner":
            return json.dumps(self.planner_response), "sess-planner"
        if role == "executor":
            self._concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self._concurrent)
            await asyncio.sleep(0.02)  # overlapni ko'rsatish uchun
            self._concurrent -= 1
            return self.executor_text, "sess-exec"
        if role == "reviewer":
            passed = True
            if self.reviewer_seq is not None:
                passed = self.reviewer_seq.pop(0) if self.reviewer_seq else True
            return json.dumps({"passed": passed, "report": "ok" if passed else "fail"}), "sess-rev"
        raise AssertionError(role)

    def count(self, role):
        return self.calls.count(role)


async def _seed_root(db, description="Vazifa"):
    t = Task(kind="root", title=description, description=description)
    await db.save_task(t)
    return t


async def _orch(db, store, runner):
    reporter = TelegramReporter(db, store)
    return Orchestrator(db, store, reporter, run_agent=runner)


async def test_happy_path_two_dependent_subtasks(db, store):
    plan = {"strategy": "x", "subtasks": [
        {"id": "s1", "title": "birinchi", "deps": []},
        {"id": "s2", "title": "ikkinchi", "deps": ["s1"]},
    ]}
    runner = FakeRunner(plan)
    orch = await _orch(db, store, runner)
    t = await _seed_root(db)

    await orch.handle_task(t)

    root = await db.get_task(t.id)
    assert root.status is TaskStatus.DONE
    subs = await db.list_subtasks(t.id)
    assert all(s.status is TaskStatus.DONE for s in subs)
    assert runner.count("planner") == 1
    assert runner.count("executor") == 2
    assert runner.count("reviewer") == 2
    assert root.strategy == "x"


async def test_independent_subtasks_run_in_parallel(db, store):
    plan = {"strategy": "p", "subtasks": [
        {"id": "s1", "title": "a", "deps": []},
        {"id": "s2", "title": "b", "deps": []},
        {"id": "s3", "title": "c", "deps": []},
    ]}
    runner = FakeRunner(plan)
    orch = await _orch(db, store, runner)
    t = await _seed_root(db)

    await orch.handle_task(t)

    assert (await db.get_task(t.id)).status is TaskStatus.DONE
    # Mustaqil subtask'lar bir vaqtda ishladi (overlap kuzatildi).
    assert runner.max_concurrent >= 2


async def test_dependent_subtask_waits(db, store):
    # s2 s1'ga bog'liq → ular hech qachon bir vaqtda ishlamaydi.
    plan = {"strategy": "p", "subtasks": [
        {"id": "s1", "title": "a", "deps": []},
        {"id": "s2", "title": "b", "deps": ["s1"]},
    ]}
    runner = FakeRunner(plan)
    orch = await _orch(db, store, runner)
    t = await _seed_root(db)
    await orch.handle_task(t)
    assert runner.max_concurrent == 1


async def test_retry_then_pass(db, store):
    plan = {"strategy": "p", "subtasks": [{"id": "s1", "title": "a", "deps": []}]}
    # Birinchi review fail, ikkinchisi pass. MAX_RETRY default 2.
    runner = FakeRunner(plan, reviewer_seq=[False, True])
    orch = await _orch(db, store, runner)
    t = await _seed_root(db)

    await orch.handle_task(t)

    assert (await db.get_task(t.id)).status is TaskStatus.DONE
    subs = await db.list_subtasks(t.id)
    assert subs[0].status is TaskStatus.DONE
    assert subs[0].attempts == 1  # bitta qayta urinish
    assert runner.count("executor") == 2  # qayta bajarildi


async def test_permanent_fail(db, store):
    plan = {"strategy": "p", "subtasks": [{"id": "s1", "title": "a", "deps": []}]}
    # MAX_RETRY=1 qilamiz → 1 dan ortiq urinishda FAILED.
    await store.set_secret("MAX_RETRY", "1", by_user="t", is_secret=False)
    runner = FakeRunner(plan, reviewer_seq=[False, False, False])
    orch = await _orch(db, store, runner)
    t = await _seed_root(db)

    await orch.handle_task(t)

    assert (await db.get_task(t.id)).status is TaskStatus.FAILED
    assert (await db.list_subtasks(t.id))[0].status is TaskStatus.FAILED


async def test_resume_is_idempotent(db, store):
    # Root allaqachon subtask'larga ega (kraш oldidan rejalashtirilgan).
    t = await _seed_root(db)
    await db.save_subtasks(t.id, [{"id": "s1", "title": "a", "deps": []}])
    await db.update_status(t.id, TaskStatus.PLANNED)

    plan = {"strategy": "QAYTA", "subtasks": [{"id": "x", "title": "yangi", "deps": []}]}
    runner = FakeRunner(plan)
    orch = await _orch(db, store, runner)

    await orch.handle_task(t)

    # Planner CHAQIRILMASLIGI kerak (qayta rejalashtirish yo'q).
    assert runner.count("planner") == 0
    subs = await db.list_subtasks(t.id)
    assert len(subs) == 1 and subs[0].title == "a"  # yangi subtask qo'shilmadi
    assert (await db.get_task(t.id)).status is TaskStatus.DONE


async def test_run_once_picks_pending(db, store):
    plan = {"strategy": "p", "subtasks": [{"id": "s1", "title": "a", "deps": []}]}
    runner = FakeRunner(plan)
    orch = await _orch(db, store, runner)
    await _seed_root(db)
    assert await orch.run_once() is True
    assert await orch.run_once() is False  # boshqa pending yo'q
