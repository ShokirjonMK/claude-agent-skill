"""Orchestra CLI — yagona entrypoint.

Buyruqlar:
  run         — orchestrator loop
  bot         — Telegram inbound bot
  web         — web admin-panel (uvicorn)
  submit "x"  — bazaga root vazifa qo'shadi
  status <id> — vazifa holatini ko'rsatadi
  createadmin <user> <parol> — admin foydalanuvchi yaratadi
  initdb      — jadvallarni yaratadi (+ bootstrap admin)
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from .chat import ChatService
from .config import get_settings
from .db import make_db
from .models import Role, Task, TaskStatus, User
from .orchestrator import Orchestrator
from .reporter import TelegramReporter
from .secrets import SecretStore


async def _bootstrap():
    settings = get_settings()
    db = make_db(settings.db_dsn)
    await db.connect()
    await db.initdb()
    store = SecretStore(db, settings)
    return settings, db, store


# ── Buyruqlar ─────────────────────────────────────────────────────────────────
async def cmd_initdb() -> None:
    from .web.auth import ensure_bootstrap_admin

    settings, db, store = await _bootstrap()
    await ensure_bootstrap_admin(db, settings)
    print("✅ Baza tayyor (jadvallar yaratildi).")
    await db.close()


async def cmd_createadmin(username: str, password: str) -> None:
    from .web.auth import hash_password

    _, db, _ = await _bootstrap()
    if await db.get_user_by_username(username):
        print(f"⚠️ '{username}' allaqachon mavjud.")
    else:
        await db.save_user(
            User(username=username, password_hash=hash_password(password), role=Role.ADMIN)
        )
        print(f"✅ Admin yaratildi: {username}")
    await db.close()


async def cmd_submit(text: str) -> None:
    _, db, _ = await _bootstrap()
    t = Task(kind="root", title=text[:80], description=text, status=TaskStatus.PENDING)
    await db.save_task(t)
    await db.log_audit(actor_type="system", actor_id=None, action="task.created", target=t.id)
    print(f"✅ Vazifa qo'shildi: {t.id}")
    await db.close()


async def cmd_status(task_id: str) -> None:
    _, db, _ = await _bootstrap()
    t = await db.get_task(task_id)
    if not t:
        # qisqartirilgan id bo'yicha qidiramiz
        for cand in await db.recent_tasks(limit=100, kind=None):
            if cand.id.startswith(task_id):
                t = cand
                break
    if not t:
        print("Topilmadi.")
    else:
        subs = await db.list_subtasks(t.id)
        done = sum(1 for s in subs if s.status is TaskStatus.DONE)
        print(f"{t.id}\n  holat: {t.status.value}\n  subtask: {done}/{len(subs)} DONE")
    await db.close()


async def cmd_run() -> None:
    settings, db, store = await _bootstrap()
    reporter = TelegramReporter(db, store)
    orch = Orchestrator(db, store, reporter)
    print("🎼 Orchestrator ishga tushdi. To'xtatish: Ctrl+C")
    try:
        await orch.run_forever()
    finally:
        await db.close()


async def cmd_bot() -> None:
    from .telegram_bot import TelegramBot

    settings, db, store = await _bootstrap()
    chat = ChatService(db, store)
    bot = TelegramBot(db, store, chat)
    print("🤖 Telegram bot ishga tushdi.")
    try:
        await bot.run()
    finally:
        await db.close()


def cmd_web() -> None:
    import uvicorn

    from .web.app import create_app
    from .web.sse import EventHub

    settings = get_settings()
    db = make_db(settings.db_dsn)
    store = SecretStore(db, settings)
    app = create_app(db, store, settings, hub=EventHub(), connect_on_startup=True)
    print(f"🌐 Web admin-panel: http://{settings.web_host}:{settings.web_port}")
    uvicorn.run(app, host=settings.web_host, port=settings.web_port)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orchestra", description="Orchestra CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("run", help="orchestrator loop")
    sub.add_parser("bot", help="Telegram bot")
    sub.add_parser("web", help="web admin-panel")
    sub.add_parser("initdb", help="bazani tayyorlash")

    p_submit = sub.add_parser("submit", help="root vazifa qo'shish")
    p_submit.add_argument("text")

    p_status = sub.add_parser("status", help="vazifa holati")
    p_status.add_argument("id")

    p_admin = sub.add_parser("createadmin", help="admin yaratish")
    p_admin.add_argument("username")
    p_admin.add_argument("password")

    args = parser.parse_args(argv)

    if args.cmd == "web":
        cmd_web()
        return 0

    coro = {
        "run": cmd_run(),
        "bot": cmd_bot(),
        "initdb": cmd_initdb(),
        "submit": cmd_submit(args.text) if args.cmd == "submit" else None,
        "status": cmd_status(args.id) if args.cmd == "status" else None,
        "createadmin": cmd_createadmin(args.username, args.password)
        if args.cmd == "createadmin"
        else None,
    }[args.cmd]
    try:
        asyncio.run(coro)
    except KeyboardInterrupt:
        print("\nTo'xtatildi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
