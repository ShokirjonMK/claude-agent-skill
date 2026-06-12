"""Chat testlari: agent bilan suhbat kontekstni (resume) saqlaydi, xabarlar yoziladi."""

from __future__ import annotations

import pytest

from orchestra.chat import ChatService


class EchoRunner:
    """chat agentni taqlid qiladi: kelgan session_id'ni eslab qoladi, javob qaytaradi."""

    def __init__(self):
        self.seen_sessions: list[str | None] = []
        self.turn = 0

    async def __call__(self, role, prompt, *, model, session_id=None, on_block=None):
        assert role == "chat"
        self.seen_sessions.append(session_id)
        self.turn += 1
        return f"javob#{self.turn}: {prompt}", f"sess-{self.turn}"


async def test_chat_persists_and_resumes(db, store):
    runner = EchoRunner()
    svc = ChatService(db, store, run_agent=runner)

    r1 = await svc.send(task_id="t1", user_text="salom", channel="telegram", user_id="u1")
    assert r1.startswith("javob#1")
    # Birinchi chaqiriqda avvalgi sessiya yo'q.
    assert runner.seen_sessions[0] is None

    r2 = await svc.send(task_id="t1", user_text="davom", channel="telegram", user_id="u1")
    assert r2.startswith("javob#2")
    # Ikkinchi chaqiriqda birinchi sessiya resume qilinadi.
    assert runner.seen_sessions[1] == "sess-1"

    msgs = await db.list_chat_messages("t1")
    # 2 ta in + 2 ta out
    assert len(msgs) == 4
    directions = [m["direction"] for m in msgs]
    assert directions == ["in", "out", "in", "out"]


async def test_chat_without_task(db, store):
    svc = ChatService(db, store, run_agent=EchoRunner())
    r = await svc.send(task_id=None, user_text="erkin savol", channel="web")
    assert "erkin savol" in r
    msgs = await db.list_chat_messages()
    assert len(msgs) == 2
