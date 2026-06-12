"""Telegram inbound — global bot + har bir server uchun alohida bot.

Buyruqlar: /task /status /tasks /chat /endchat. Har bir server o'z bot tokeni bilan
ishlaydi; o'sha bot orqali yuborilgan vazifalar shu serverga bog'lanadi va har bir
qadam shu botga yuboriladi. Vazifalar nom + qisqa tracking kodi (T-ab123) oladi.

`BotManager` global va per-server botlarni bitta jarayonda boshqaradi va konfiguratsiya
o'zgarganda (yangi server/token) avtomatik moslashadi.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from .chat import ChatService
from .db import AsyncDB
from .models import Task, TaskStatus, new_code
from .secrets import SecretStore

Send = Callable[[str], Awaitable[None]]

HELP = (
    "🤖 *Orchestra*\n"
    "/task <matn> — yangi vazifa\n"
    "/status <kod yoki id> — holat\n"
    "/tasks — oxirgi 10 ta\n"
    "/chat <kod> — agent bilan suhbat (muammoni hal qilish)\n"
    "/endchat — suhbatni tugatish"
)


class TelegramBot:
    """Bitta bot (global yoki bitta serverga bog'langan) buyruq mantig'i."""

    def __init__(
        self,
        db: AsyncDB,
        store: SecretStore,
        chat: ChatService,
        *,
        scope_server_id: str | None = None,
        scope_prefix: str = "T",
        scope_label: str = "global",
    ):
        self._db = db
        self._store = store
        self._chat = chat
        self._scope_server_id = scope_server_id
        self._scope_prefix = scope_prefix
        self._scope_label = scope_label
        self._chat_mode: dict[str, str | None] = {}

    async def on_message(
        self, chat_id: str, text: str, send: Send, *, user_id: str | None = None
    ) -> None:
        text = (text or "").strip()
        if not text:
            return
        if not await self._authorized(chat_id, user_id):
            await send("⛔ Ruxsat yo'q. Administrator sizni ruxsat ro'yxatiga qo'shishi kerak.")
            await self._db.log_audit(
                actor_type="system", actor_id=str(user_id), action="telegram.unauthorized",
                details={"chat_id": chat_id, "scope": self._scope_label},
            )
            return

        if text.startswith("/"):
            await self._handle_command(chat_id, text, send, user_id=user_id)
            return

        if chat_id in self._chat_mode:
            task_id = self._chat_mode[chat_id]
            reply = await self._chat.send(
                task_id=task_id, user_text=text, channel="telegram",
                user_id=user_id, context=await self._server_context(),
            )
            await send(reply)
        else:
            await send("Buyruq kutilyapti. " + HELP)

    async def _authorized(self, chat_id: str, user_id: str | None) -> bool:
        """Per-server bot uchun: shu serverning chat_id si ruxsatli. Global uchun:
        TG_CHAT_ID + TG_ALLOWED_IDS. Bo'sh bo'lsa — rad (xavfsiz default)."""
        allowed: set[str] = set()
        if self._scope_server_id:
            srv = await self._db.get_server(self._scope_server_id)
            if srv and srv.tg_chat_id:
                allowed.add(str(srv.tg_chat_id).strip())
        else:
            cid = await self._store.get_config("TG_CHAT_ID")
            if cid:
                allowed.add(str(cid).strip())
        ids = await self._store.get_config("TG_ALLOWED_IDS")
        if ids:
            allowed |= {x.strip() for x in str(ids).split(",") if x.strip()}
        if not allowed:
            return False
        return str(chat_id) in allowed or (user_id is not None and str(user_id) in allowed)

    async def _server_context(self) -> str | None:
        if not self._scope_server_id:
            return None
        srv = await self._db.get_server(self._scope_server_id)
        if not srv:
            return None
        return (
            f"Bu suhbat '{srv.name}' serveri ({srv.host}) haqida. "
            f"Server bilan bog'liq muammoni tahlil qilib, yechim taklif qil."
        )

    async def _handle_command(
        self, chat_id: str, text: str, send: Send, *, user_id: str | None
    ) -> None:
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/start", "/help"):
            scope = f"\n📍 Server: *{self._scope_label}*" if self._scope_server_id else ""
            await send(HELP + scope)

        elif cmd == "/task":
            if not arg:
                await send("Foydalanish: /task <vazifa matni>")
                return
            t = Task(
                kind="root", title=arg[:80], description=arg, status=TaskStatus.PENDING,
                code=new_code(self._scope_prefix), server_id=self._scope_server_id,
            )
            await self._db.save_task(t)
            await self._db.log_audit(
                actor_type="user", actor_id=user_id or chat_id, action="task.created",
                target=t.id, details={"channel": "telegram", "server": self._scope_label, "code": t.code},
            )
            await send(f"✅ Vazifa qabul qilindi: *{t.code}* (`{t.id[:8]}`)\nHolat: PENDING")

        elif cmd == "/status":
            if not arg:
                await send("Foydalanish: /status <kod yoki id>")
                return
            t = await self._db.get_task_by_ref(arg)
            if not t:
                await send("Topilmadi.")
                return
            subs = await self._db.list_subtasks(t.id)
            done = sum(1 for s in subs if s.status is TaskStatus.DONE)
            await send(
                f"📋 *{t.code or t.id[:8]}* — *{t.status.value}*\n{t.title}\n"
                f"Subtasklar: {done}/{len(subs)} DONE"
            )

        elif cmd == "/tasks":
            recent = await self._db.recent_tasks(limit=10, server_id=self._scope_server_id)
            if not recent:
                await send("Vazifalar yo'q.")
                return
            lines = [f"*{t.code or t.id[:8]}* {t.status.value} — {t.title[:36]}" for t in recent]
            await send("📋 Oxirgi vazifalar:\n" + "\n".join(lines))

        elif cmd == "/chat":
            task_id = None
            if arg:
                t = await self._db.get_task_by_ref(arg)
                if not t:
                    await send("Bunday vazifa topilmadi.")
                    return
                task_id = t.id
            self._chat_mode[chat_id] = task_id
            tip = f" (vazifa)" if task_id else (f" (server: {self._scope_label})" if self._scope_server_id else "")
            await send(f"💬 Suhbat rejimi yoqildi{tip}. /endchat — chiqish.")

        elif cmd == "/endchat":
            self._chat_mode.pop(chat_id, None)
            await send("Suhbat tugatildi.")

        else:
            await send("Noma'lum buyruq.\n" + HELP)


# ── Bitta token uchun long-polling ───────────────────────────────────────────
async def _poll_bot(bot: TelegramBot, token: str, *, stop_event: asyncio.Event) -> None:
    import httpx

    base = f"https://api.telegram.org/bot{token}"
    offset = 0
    async with httpx.AsyncClient(timeout=40) as client:
        while not stop_event.is_set():
            try:
                resp = await client.get(
                    f"{base}/getUpdates", params={"offset": offset, "timeout": 25}
                )
                data = resp.json()
            except Exception:
                await asyncio.sleep(3)
                continue
            if not data.get("ok"):
                await asyncio.sleep(5)
                continue
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("edited_message")
                if not msg:
                    continue
                cid = str(msg["chat"]["id"])
                txt = msg.get("text", "")
                uid = str(msg.get("from", {}).get("id", cid))

                async def send(reply: str, _cid=cid, _base=base) -> None:
                    await client.post(
                        f"{_base}/sendMessage",
                        json={"chat_id": _cid, "text": reply, "parse_mode": "Markdown"},
                    )

                try:
                    await bot.on_message(cid, txt, send, user_id=uid)
                except Exception as exc:  # noqa: BLE001
                    await send(f"Xatolik: {exc}")


# ── Multi-bot menejer ─────────────────────────────────────────────────────────
class BotManager:
    """Global va per-server botlarni bitta jarayonda boshqaradi; konfiguratsiya
    o'zgarsa (token/yangi server) ~15s ichida moslashadi."""

    def __init__(self, db: AsyncDB, store: SecretStore):
        self._db = db
        self._store = store

    async def _desired(self) -> dict[str, dict]:
        """token → {bot, scope} konfiguratsiyalari."""
        out: dict[str, dict] = {}
        # Global bot
        enabled = (await self._store.get_config("TG_BOT_ENABLED", "1")) not in (
            "0", "false", "False", "off", "no",
        )
        gtok = await self._store.get_config("TG_BOT_TOKEN")
        if gtok and enabled:
            out[gtok] = {"scope_server_id": None, "scope_prefix": "T", "label": "global"}
        # Per-server botlar
        for srv in await self._db.servers_with_bots():
            tok = await self._store.get_secret(srv.tg_token_ref) if srv.tg_token_ref else None
            if tok:
                out[tok] = {
                    "scope_server_id": srv.id,
                    "scope_prefix": srv.name or "SRV",
                    "label": srv.name or srv.host,
                }
        return out

    async def run(self, *, stop_event: asyncio.Event | None = None) -> None:
        running: dict[str, tuple[asyncio.Task, asyncio.Event]] = {}
        print("🤖 Telegram BotManager ishga tushdi (global + per-server).")
        try:
            while stop_event is None or not stop_event.is_set():
                desired = await self._desired()
                # Yangi botlarni ishga tushirish
                for token, cfg in desired.items():
                    if token not in running or running[token][0].done():
                        ev = asyncio.Event()
                        chat = ChatService(self._db, self._store)
                        bot = TelegramBot(
                            self._db, self._store, chat,
                            scope_server_id=cfg["scope_server_id"],
                            scope_prefix=cfg["scope_prefix"],
                            scope_label=cfg["label"],
                        )
                        task = asyncio.create_task(_poll_bot(bot, token, stop_event=ev))
                        running[token] = (task, ev)
                        print(f"  ▶ bot start: {cfg['label']}")
                # Olib tashlangan botlarni to'xtatish
                for token in list(running):
                    if token not in desired:
                        task, ev = running.pop(token)
                        ev.set()
                        task.cancel()
                        print("  ⏹ bot stop")
                await asyncio.sleep(15)
        finally:
            for _token, (task, ev) in running.items():
                ev.set()
                task.cancel()
