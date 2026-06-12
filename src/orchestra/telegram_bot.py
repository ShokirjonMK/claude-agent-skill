"""Telegram inbound bot — ikki tomonlama interfeys.

Buyruqlar:
  /task <matn>     — yangi root vazifa (PENDING)
  /status <id>     — vazifa holati
  /tasks           — oxirgi 10 ta vazifa
  /chat <task_id>  — agent bilan suhbat rejimi (kontekst saqlanadi)
  /endchat         — suhbatni tugatish

Buyruq mantig'i (`on_message`) `send` callback orqali javob beradi va to'liq
testlanadi; `run` esa long-polling (getUpdates) bilan haqiqiy Telegram'ga ulanadi.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from .chat import ChatService
from .db import AsyncDB
from .models import Task, TaskStatus
from .secrets import SecretStore

Send = Callable[[str], Awaitable[None]]

HELP = (
    "🤖 *Orchestra*\n"
    "/task <matn> — yangi vazifa\n"
    "/status <id> — holat\n"
    "/tasks — oxirgi 10 ta\n"
    "/chat <task_id> — agent bilan suhbat\n"
    "/endchat — suhbatni tugatish"
)


class TelegramBot:
    def __init__(self, db: AsyncDB, store: SecretStore, chat: ChatService):
        self._db = db
        self._store = store
        self._chat = chat
        # chat_id → suhbat rejimidagi task_id
        self._chat_mode: dict[str, str | None] = {}

    async def on_message(
        self, chat_id: str, text: str, send: Send, *, user_id: str | None = None
    ) -> None:
        text = (text or "").strip()
        if not text:
            return

        if text.startswith("/"):
            await self._handle_command(chat_id, text, send, user_id=user_id)
            return

        # Buyruq emas — suhbat rejimida bo'lsa chat agentga uzatamiz.
        if chat_id in self._chat_mode:
            task_id = self._chat_mode[chat_id]
            reply = await self._chat.send(
                task_id=task_id, user_text=text, channel="telegram", user_id=user_id
            )
            await send(reply)
        else:
            await send("Buyruq kutilyapti. " + HELP)

    async def _handle_command(
        self, chat_id: str, text: str, send: Send, *, user_id: str | None
    ) -> None:
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/start", "/help"):
            await send(HELP)

        elif cmd == "/task":
            if not arg:
                await send("Foydalanish: /task <vazifa matni>")
                return
            t = Task(kind="root", title=arg[:80], description=arg, status=TaskStatus.PENDING)
            await self._db.save_task(t)
            await self._db.log_audit(
                actor_type="user", actor_id=user_id or chat_id,
                action="task.created", target=t.id, details={"channel": "telegram"},
            )
            await send(f"✅ Vazifa qabul qilindi: `{t.id[:8]}`\nHolat: PENDING")

        elif cmd == "/status":
            if not arg:
                await send("Foydalanish: /status <id>")
                return
            t = await self._find_task(arg)
            if not t:
                await send("Topilmadi.")
                return
            subs = await self._db.list_subtasks(t.id)
            done = sum(1 for s in subs if s.status is TaskStatus.DONE)
            await send(
                f"📋 `{t.id[:8]}` — *{t.status.value}*\n"
                f"{t.title}\n"
                f"Subtasklar: {done}/{len(subs)} DONE"
            )

        elif cmd == "/tasks":
            recent = await self._db.recent_tasks(limit=10)
            if not recent:
                await send("Vazifalar yo'q.")
                return
            lines = [f"`{t.id[:8]}` {t.status.value} — {t.title[:40]}" for t in recent]
            await send("📋 Oxirgi vazifalar:\n" + "\n".join(lines))

        elif cmd == "/chat":
            task_id = None
            if arg:
                t = await self._find_task(arg)
                if not t:
                    await send("Bunday vazifa topilmadi.")
                    return
                task_id = t.id
            self._chat_mode[chat_id] = task_id
            tip = f" (task `{task_id[:8]}`)" if task_id else ""
            await send(f"💬 Suhbat rejimi yoqildi{tip}. /endchat — chiqish.")

        elif cmd == "/endchat":
            self._chat_mode.pop(chat_id, None)
            await send("Suhbat tugatildi.")

        else:
            await send("Noma'lum buyruq.\n" + HELP)

    async def _find_task(self, ref: str) -> Task | None:
        """To'liq yoki qisqartirilgan (8 belgi) id bo'yicha vazifa topadi."""
        t = await self._db.get_task(ref)
        if t:
            return t
        for cand in await self._db.recent_tasks(limit=50, kind=None):
            if cand.id.startswith(ref):
                return cand
        return None

    # ── Long-polling (haqiqiy Telegram) ──────────────────────────────────────
    async def run(self, *, stop_event: asyncio.Event | None = None) -> None:
        import httpx

        # Token Secrets'dan dinamik keladi — yo'q bo'lsa CRASH qilmaymiz, kutamiz.
        token = await self._store.get_config("TG_BOT_TOKEN")
        while not token:
            print("⏳ TG_BOT_TOKEN kutilyapti (Secrets sahifasidan kiriting)…")
            await asyncio.sleep(15)
            if stop_event is not None and stop_event.is_set():
                return
            token = await self._store.get_config("TG_BOT_TOKEN")
        base = f"https://api.telegram.org/bot{token}"
        offset = 0
        async with httpx.AsyncClient(timeout=40) as client:
            while stop_event is None or not stop_event.is_set():
                try:
                    resp = await client.get(
                        f"{base}/getUpdates", params={"offset": offset, "timeout": 30}
                    )
                    data = resp.json()
                except Exception:
                    await asyncio.sleep(3)
                    continue
                for upd in data.get("result", []):
                    offset = upd["update_id"] + 1
                    msg = upd.get("message") or upd.get("edited_message")
                    if not msg:
                        continue
                    chat_id = str(msg["chat"]["id"])
                    text = msg.get("text", "")
                    user_id = str(msg.get("from", {}).get("id", chat_id))

                    async def send(reply: str, _cid=chat_id) -> None:
                        await client.post(
                            f"{base}/sendMessage",
                            json={"chat_id": _cid, "text": reply, "parse_mode": "Markdown"},
                        )

                    try:
                        await self.on_message(chat_id, text, send, user_id=user_id)
                    except Exception as exc:  # noqa: BLE001
                        await send(f"Xatolik: {exc}")
