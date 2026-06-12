"""Telegram bot buyruqlari + avtorizatsiya testi (on_message), haqiqiy TG'siz."""

from __future__ import annotations

import pytest
import pytest_asyncio

from orchestra.chat import ChatService
from orchestra.models import TaskStatus
from orchestra.telegram_bot import TelegramBot


class EchoRunner:
    async def __call__(self, role, prompt, *, model, session_id=None, on_block=None):
        return f"echo: {prompt}", "sess-1"


@pytest_asyncio.fixture
async def bot(db, store):
    # Chat "100" ni ruxsat ro'yxatiga qo'shamiz (aks holda bot rad etadi — xavfsiz default).
    await store.set_secret("TG_ALLOWED_IDS", "100", by_user=None, is_secret=False)
    chat = ChatService(db, store, run_agent=EchoRunner())
    return TelegramBot(db, store, chat)


class Collector:
    def __init__(self):
        self.replies = []

    async def __call__(self, text):
        self.replies.append(text)


async def test_unauthorized_user_blocked(db, store):
    # Allowlist bo'sh → hammaga rad.
    chat = ChatService(db, store, run_agent=EchoRunner())
    b = TelegramBot(db, store, chat)
    send = Collector()
    await b.on_message("999", "/task zararli", send, user_id="hacker")
    assert any("Ruxsat yo'q" in r for r in send.replies)
    # Vazifa YARATILMASLIGI kerak.
    assert await db.recent_tasks() == []


async def test_authorized_chat_allowed(db, store):
    await store.set_secret("TG_CHAT_ID", "777", by_user=None, is_secret=False)
    chat = ChatService(db, store, run_agent=EchoRunner())
    b = TelegramBot(db, store, chat)
    send = Collector()
    await b.on_message("777", "/tasks", send)
    assert not any("Ruxsat yo'q" in r for r in send.replies)


async def test_task_command_creates_task(bot, db):
    send = Collector()
    await bot.on_message("100", "/task PDF generatorini yoz", send, user_id="u1")
    assert any("qabul qilindi" in r for r in send.replies)
    tasks = await db.recent_tasks()
    assert len(tasks) == 1 and tasks[0].status is TaskStatus.PENDING


async def test_status_command(bot, db):
    send = Collector()
    await bot.on_message("100", "/task X", send, user_id="u1")
    tid = (await db.recent_tasks())[0].id
    send2 = Collector()
    await bot.on_message("100", f"/status {tid[:8]}", send2)
    assert any("PENDING" in r for r in send2.replies)


async def test_tasks_command_empty_and_list(bot, db):
    send = Collector()
    await bot.on_message("100", "/tasks", send)
    assert any("yo'q" in r for r in send.replies)
    await bot.on_message("100", "/task A", Collector())
    send2 = Collector()
    await bot.on_message("100", "/tasks", send2)
    assert any("Oxirgi vazifalar" in r for r in send2.replies)


async def test_chat_mode_routes_to_agent(bot, db):
    await bot.on_message("100", "/task A", Collector())
    tid = (await db.recent_tasks())[0].id
    send = Collector()
    await bot.on_message("100", f"/chat {tid[:8]}", send)
    assert any("Suhbat rejimi" in r for r in send.replies)
    send2 = Collector()
    await bot.on_message("100", "muammo bor", send2)
    assert any(r.startswith("echo:") for r in send2.replies)
    send3 = Collector()
    await bot.on_message("100", "/endchat", send3)
    assert any("tugatildi" in r for r in send3.replies)


async def test_plain_text_without_chat_shows_help(bot):
    send = Collector()
    await bot.on_message("100", "shunchaki matn", send)
    assert any("Buyruq kutilyapti" in r for r in send.replies)


async def test_unknown_command(bot):
    send = Collector()
    await bot.on_message("100", "/foobar", send)
    assert any("Noma'lum" in r for r in send.replies)
