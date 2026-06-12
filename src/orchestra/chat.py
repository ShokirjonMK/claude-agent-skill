"""Agent bilan suhbat (muammolarni hal qilish).

Foydalanuvchi xabari `chat` agentga uzatiladi; kontekst SDK `resume` (session_id) orqali
saqlanadi. Har xabar `chat_messages`'ga (in/out) yoziladi. TG va Web ikkalasi ishlatadi.
"""

from __future__ import annotations

import os
from typing import Awaitable, Callable

from .agents import AGENT_SPECS
from .db import AsyncDB
from .secrets import SecretStore

RunAgentFn = Callable[..., Awaitable[tuple[str, "str | None"]]]


class ChatService:
    def __init__(
        self,
        db: AsyncDB,
        store: SecretStore,
        *,
        run_agent: RunAgentFn | None = None,
    ):
        self._db = db
        self._store = store
        if run_agent is None:
            from .runner import run_agent as _ra

            run_agent = _ra
        self._run_agent = run_agent

    async def send(
        self,
        *,
        task_id: str | None,
        user_text: str,
        channel: str,  # 'telegram' | 'web'
        user_id: str | None = None,
        context: str | None = None,
    ) -> str:
        """Foydalanuvchi xabarini yuboradi, agent javobini qaytaradi (kontekst saqlanadi)."""
        # Avvalgi suhbat sessiyasini (resume uchun) topamiz.
        prev_session = (
            await self._db.latest_chat_session(task_id) if task_id else None
        )

        await self._db.save_chat_message(
            task_id=task_id, chat_session_id=prev_session, channel=channel,
            direction="in", role="user", content=user_text, user_id=user_id,
        )

        model = await self._store.get_config(
            AGENT_SPECS["chat"].model_key, AGENT_SPECS["chat"].default_model
        )
        # SDK ANTHROPIC_API_KEY ni env'dan o'qiydi — dinamik secret'ni joylaymiz.
        api_key = await self._store.get_config("ANTHROPIC_API_KEY")
        if api_key:
            os.environ["ANTHROPIC_API_KEY"] = api_key
        prompt = self._build_prompt(task_id, user_text)
        if context and not prev_session:
            # Suhbat boshida server/kontekst ma'lumotini qo'shamiz (faqat birinchi xabarda).
            prompt = f"[KONTEKST] {context}\n\n{prompt}"
        reply, new_session = await self._run_agent(
            "chat", prompt, model=model, session_id=prev_session
        )

        await self._db.save_chat_message(
            task_id=task_id, chat_session_id=new_session or prev_session, channel=channel,
            direction="out", role="agent", content=reply, user_id=user_id,
        )
        await self._db.log_audit(
            actor_type="user", actor_id=user_id, action="chat.message",
            target=task_id, details={"channel": channel},
        )
        return reply

    def _build_prompt(self, task_id: str | None, user_text: str) -> str:
        if task_id:
            return f"[task {task_id[:8]}] {user_text}"
        return user_text
