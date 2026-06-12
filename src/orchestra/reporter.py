"""Telegram outbound hisobot + audit + real-vaqt broadcast.

Har holat o'zgarishi: `events` jadvaliga yoziladi, `audit_log`'ga (actor=agent) yoziladi,
web SSE broadcaster'ga uzatiladi va (token bo'lsa) Telegram'ga yuboriladi.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from .db import AsyncDB
from .secrets import SecretStore

Broadcaster = Callable[[dict], Awaitable[None]]


class TelegramReporter:
    def __init__(
        self,
        db: AsyncDB,
        store: SecretStore,
        *,
        broadcaster: Broadcaster | None = None,
        http: Any = None,
    ):
        self._db = db
        self._store = store
        self._broadcaster = broadcaster
        self._http = http  # ixtiyoriy httpx.AsyncClient (test/inj uchun)

    async def report(
        self, *, agent_id: str | None, role: str, task_id: str | None, status_text: str
    ) -> None:
        """Bitta holat hisoboti."""
        await self._db.log_event(task_id, agent_id, role, status_text)
        await self._db.log_audit(
            actor_type="agent",
            actor_id=agent_id,
            action=f"agent.{role}",
            target=task_id,
            details={"status": status_text},
        )
        if self._broadcaster:
            await self._broadcaster(
                {
                    "type": "report",
                    "role": role,
                    "agent_id": agent_id,
                    "task_id": task_id,
                    "status": status_text,
                }
            )
        token, chat_id = await self._resolve_target(task_id)
        # Vazifa kodi (tracking) bo'lsa sarlavhaga qo'shamiz.
        label = await self._task_label(task_id)
        await self._send_telegram(
            f"🤖 *{role}* `{agent_id or '-'}`\n"
            f"📋 {label}\n"
            f"{status_text}",
            token, chat_id,
        )

    async def warn(self, text: str, *, task_id: str | None = None) -> None:
        """Ogohlantirish (masalan xavfli komanda bloklandi)."""
        await self._db.log_event(task_id, None, "WARN", text)
        await self._db.log_audit(
            actor_type="system", actor_id=None, action="guard.block",
            target=task_id, details={"text": text},
        )
        if self._broadcaster:
            await self._broadcaster({"type": "warn", "task_id": task_id, "text": text})
        token, chat_id = await self._resolve_target(task_id)
        await self._send_telegram(f"⚠️ {text}", token, chat_id)

    async def _resolve_target(self, task_id: str | None) -> tuple[str | None, str | None]:
        """Vazifa serverga bog'langan bo'lsa — o'sha serverning boti/chat'i, aks holda umumiy."""
        if task_id:
            task = await self._db.get_task(task_id)
            if task and task.server_id:
                srv = await self._db.get_server(task.server_id)
                if srv and srv.tg_token_ref:
                    tok = await self._store.get_secret(srv.tg_token_ref)
                    if tok:
                        return tok, srv.tg_chat_id
        token = await self._store.get_config("TG_BOT_TOKEN")
        chat_id = await self._store.get_config("TG_CHAT_ID")
        return token, chat_id

    async def _task_label(self, task_id: str | None) -> str:
        if not task_id:
            return "task -"
        task = await self._db.get_task(task_id)
        if task and task.code:
            return f"*{task.code}* — {task.title[:40]}"
        return f"task `{(task_id or '')[:8]}`"

    async def _send_telegram(
        self, text: str, token: str | None = None, chat_id: str | None = None
    ) -> None:
        if not token or not chat_id:
            return  # sozlanmagan — jim o'tkazib yuboramiz (event baribir yozilgan)
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        try:
            if self._http is not None:
                await self._http.post(url, json=payload, timeout=10)
            else:
                import httpx

                async with httpx.AsyncClient() as client:
                    await client.post(url, json=payload, timeout=10)
        except Exception:
            # Hisobot yuborilmasa ham orchestrator to'xtamaydi (event yozilgan).
            pass
