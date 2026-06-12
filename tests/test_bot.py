"""Telegram bot buyruqlari testi (on_message), haqiqiy TG'siz."""

from __future__ import annotations

import pytest

from orchestra.chat import ChatService
from orchestra.models import TaskStatus
from orchestra.telegram_bot import TelegramBot


class EchoRunner:
    async def __call__(self, role, prompt, *, model, session_id=None, on_block=None):
        return f"echo: {prompt}", "sess-1"


def make_bot(db, store):
    chat = ChatService(db, store, run_agent=EchoRunner())
    return TelegramBot(db, store, chat)


class Collector:
    def __init__(self):
        self.replies = []

    async def __call__(self, text):
        self.replies.append(text)


async def test_task_command_creates_task(db, store):
    bot = make_bot(db, store)
    send = Collector()
    await bot.on_message("100", "/task PDF generatorini yoz", send, user_id="u1")
    assert any("qabul qilindi" in r for r in send.replies)
    tasks = await db.recent_tasks()
    assert len(tasks) == 1 and tasks[0].status is TaskStatus.PENDING


async def test_status_command(db, store):
    bot = make_bot(db, store)
    send = Collector()
    await bot.on_message("100", "/task X", send, user_id="u1")
    tid = (await db.recent_tasks())[0].id
    send2 = Collector()
    await bot.on_message("100", f"/status {tid[:8]}", send2)
    assert any("PENDING" in r for r in send2.replies)


async def test_tasks_command_empty_and_list(db, store):
    bot = make_bot(db, store)
    send = Collector()
    await bot.on_message("100", "/tasks", send)
    assert any("yo'q" in r for r in send.replies)
    await bot.on_message("100", "/task A", Collector())
    send2 = Collector()
    await bot.on_message("100", "/tasks", send2)
    assert any("Oxirgi vazifalar" in r for r in send2.replies)


async def test_chat_mode_routes_to_agent(db, store):
    bot = make_bot(db, store)
    # vazifa yaratamiz
    await bot.on_message("100", "/task A", Collector())
    tid = (await db.recent_tasks())[0].id
    # suhbat rejimi
    send = Collector()
    await bot.on_message("100", f"/chat {tid[:8]}", send)
    assert any("Suhbat rejimi" in r for r in send.replies)
    # endi oddiy matn chat agentga boradi
    send2 = Collector()
    await bot.on_message("100", "muammo bor", send2)
    assert any(r.startswith("echo:") for r in send2.replies)
    # endchat
    send3 = Collector()
    await bot.on_message("100", "/endchat", send3)
    assert any("tugatildi" in r for r in send3.replies)


async def test_plain_text_without_chat_shows_help(db, store):
    bot = make_bot(db, store)
    send = Collector()
    await bot.on_message("100", "shunchaki matn", send)
    assert any("Buyruq kutilyapti" in r for r in send.replies)


async def test_unknown_command(db, store):
    bot = make_bot(db, store)
    send = Collector()
    await bot.on_message("100", "/foobar", send)
    assert any("Noma'lum" in r for r in send.replies)
