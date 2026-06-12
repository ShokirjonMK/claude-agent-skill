"""Per-server bot, tracking kodi va reporter yo'naltirish testlari."""

from __future__ import annotations

import pytest

from orchestra.chat import ChatService
from orchestra.models import Server, Task, TaskStatus, new_code
from orchestra.reporter import TelegramReporter
from orchestra.telegram_bot import TelegramBot


class EchoRunner:
    async def __call__(self, role, prompt, *, model, session_id=None, on_block=None):
        return f"echo: {prompt}", "s1"


# ── Tracking kodi va ref bo'yicha qidirish ────────────────────────────────────
def test_new_code_format():
    c = new_code("prod")
    assert c.startswith("PROD-") and len(c) == len("PROD-") + 5


async def test_get_task_by_ref(db):
    t = Task(kind="root", title="x", code="T-abc12")
    await db.save_task(t)
    assert (await db.get_task_by_ref("T-abc12")).id == t.id  # kod bo'yicha
    assert (await db.get_task_by_ref(t.id)).id == t.id        # to'liq id
    assert (await db.get_task_by_ref(t.id[:8])).id == t.id    # qisqa id
    assert await db.get_task_by_ref("yoq") is None


async def test_recent_tasks_server_filter(db):
    await db.save_task(Task(kind="root", title="a", server_id="srv1"))
    await db.save_task(Task(kind="root", title="b", server_id="srv2"))
    await db.save_task(Task(kind="root", title="c"))
    s1 = await db.recent_tasks(server_id="srv1")
    assert len(s1) == 1 and s1[0].title == "a"


async def test_servers_with_bots(db):
    await db.save_server(Server(name="nobot", host="1.1.1.1", username="r"))
    await db.save_server(Server(name="bot", host="2.2.2.2", username="r",
                                tg_token_ref="SRVTG_x", tg_chat_id="555"))
    bots = await db.servers_with_bots()
    assert len(bots) == 1 and bots[0].name == "bot"


# ── Per-server bot scope: vazifa serverga bog'lanadi + kod prefiksi ───────────
async def test_server_bot_scopes_task(db, store):
    srv = Server(name="prod", host="9.9.9.9", username="r", tg_chat_id="555",
                 tg_token_ref="SRVTG_p")
    await db.save_server(srv)
    chat = ChatService(db, store, run_agent=EchoRunner())
    bot = TelegramBot(db, store, chat, scope_server_id=srv.id, scope_prefix="prod",
                      scope_label="prod")

    sent = []
    async def send(t): sent.append(t)
    # srv.tg_chat_id = "555" → faqat 555 ruxsatli
    await bot.on_message("555", "/task serverni tekshir", send, user_id="u1")
    assert any("qabul qilindi" in s for s in sent)
    tasks = await db.recent_tasks(server_id=srv.id)
    assert len(tasks) == 1
    assert tasks[0].server_id == srv.id
    assert tasks[0].code.startswith("PROD-")


async def test_server_bot_unauthorized_chat(db, store):
    srv = Server(name="prod", host="9.9.9.9", username="r", tg_chat_id="555")
    await db.save_server(srv)
    bot = TelegramBot(db, store, ChatService(db, store, run_agent=EchoRunner()),
                      scope_server_id=srv.id, scope_label="prod")
    sent = []
    async def send(t): sent.append(t)
    await bot.on_message("999", "/task hack", send, user_id="x")  # ruxsatsiz chat
    assert any("Ruxsat yo'q" in s for s in sent)
    assert await db.recent_tasks(server_id=srv.id) == []


# ── Reporter: vazifa serverга bog'langan bo'lsa, server botiga yo'naltiriladi ──
async def test_reporter_routes_to_server_bot(db, store):
    srv = Server(name="prod", host="9.9.9.9", username="r", tg_chat_id="555",
                 tg_token_ref="SRVTG_p")
    await db.save_server(srv)
    await store.set_secret("SRVTG_p", "server-bot-token", by_user=None, is_secret=True)
    t = Task(kind="root", title="x", code="PROD-aa111", server_id=srv.id)
    await db.save_task(t)

    rep = TelegramReporter(db, store)
    tok, chat = await rep._resolve_target(t.id)
    assert tok == "server-bot-token" and chat == "555"

    # Serversiz vazifa → global
    await store.set_secret("TG_BOT_TOKEN", "global-token", by_user=None, is_secret=False)
    await store.set_secret("TG_CHAT_ID", "100", by_user=None, is_secret=False)
    t2 = Task(kind="root", title="y", code="T-bb222")
    await db.save_task(t2)
    tok2, chat2 = await rep._resolve_target(t2.id)
    assert tok2 == "global-token" and chat2 == "100"
