"""DB qatlami testlari: jadvallar, CRUD, next_pending, idempotent resume, deps moslash."""

from __future__ import annotations

import pytest

from orchestra.models import Role, Server, Task, TaskStatus, User


async def test_initdb_creates_tables(db):
    # initdb conftest'da chaqirilgan — oddiy so'rov ishlashi kerak.
    assert await db.next_pending_root() is None


async def test_save_and_get_task(db):
    t = Task(kind="root", title="Build X", description="Do the thing")
    await db.save_task(t)
    got = await db.get_task(t.id)
    assert got is not None
    assert got.title == "Build X"
    assert got.status is TaskStatus.PENDING
    assert got.created_at is not None


async def test_next_pending_root_skips_terminal(db):
    done = Task(kind="root", title="done", status=TaskStatus.DONE)
    pending = Task(kind="root", title="pending")
    await db.save_task(done)
    await db.save_task(pending)
    nxt = await db.next_pending_root()
    assert nxt is not None and nxt.id == pending.id


async def test_update_status_and_result(db):
    t = Task(kind="root", title="x")
    await db.save_task(t)
    await db.update_status(t.id, TaskStatus.EXECUTING, agent_id="executor-aa11bb")
    await db.set_result(t.id, "natija")
    got = await db.get_task(t.id)
    assert got.status is TaskStatus.EXECUTING
    assert got.agent_id == "executor-aa11bb"
    assert got.result == "natija"


async def test_increment_attempts(db):
    t = Task(kind="root", title="x")
    await db.save_task(t)
    assert await db.increment_attempts(t.id) == 1
    assert await db.increment_attempts(t.id) == 2


async def test_subtasks_dep_mapping_and_idempotent_resume(db):
    root = Task(kind="root", title="root")
    await db.save_task(root)
    assert await db.has_subtasks(root.id) is False

    subtasks = [
        {"id": "s1", "title": "first", "deps": []},
        {"id": "s2", "title": "second", "deps": ["s1"]},
    ]
    created = await db.save_subtasks(root.id, subtasks)
    assert len(created) == 2
    assert await db.has_subtasks(root.id) is True

    listed = await db.list_subtasks(root.id)
    by_title = {t.title: t for t in listed}
    # s2.deps endi s1'ning UUID'iga ishora qilishi kerak (local id emas).
    assert by_title["second"].deps == [by_title["first"].id]
    assert by_title["first"].deps == []


async def test_agent_runs_lifecycle(db):
    t = Task(kind="root", title="x")
    await db.save_task(t)
    run = await db.start_agent_run(t.id, "executor", "claude-sonnet-4-6")
    assert run.id.startswith("executor-")
    active = await db.active_agent_runs()
    assert any(r["id"] == run.id for r in active)
    await db.finish_agent_run(run.id, "done")
    assert all(r["id"] != run.id for r in await db.active_agent_runs())


async def test_events_and_audit(db):
    await db.log_event("t1", "planner-aa", "ANALYZING", "tahlil")
    evts = await db.list_events("t1")
    assert len(evts) == 1 and evts[0]["message"] == "tahlil"

    await db.log_audit(actor_type="user", actor_id="u1", action="task.created", target="t1")
    audit = await db.list_audit()
    assert audit[0]["action"] == "task.created"


async def test_users_crud(db):
    u = User(username="alice", password_hash="hash", role=Role.OPERATOR)
    await db.save_user(u)
    got = await db.get_user_by_username("alice")
    assert got is not None and got.role is Role.OPERATOR and got.is_active is True
    await db.touch_login(got.id)
    assert (await db.get_user(got.id)).last_login is not None


async def test_servers_and_ssh_audit(db):
    s = Server(name="prod", host="1.2.3.4", username="root", auth_method="key", secret_ref="SSH_KEY_PROD")
    await db.save_server(s)
    assert (await db.get_server(s.id)).host == "1.2.3.4"
    await db.log_ssh_command(s.id, "u1", "ls -la", "out", 0, 12)
    cmds = await db.list_ssh_commands(s.id)
    assert len(cmds) == 1 and cmds[0]["exit_code"] == 0


async def test_chat_messages_and_session(db):
    await db.save_chat_message(
        task_id="t1", chat_session_id="sess-1", channel="telegram",
        direction="in", role="user", content="salom",
    )
    await db.save_chat_message(
        task_id="t1", chat_session_id="sess-1", channel="telegram",
        direction="out", role="agent", content="javob",
    )
    msgs = await db.list_chat_messages("t1")
    assert len(msgs) == 2
    assert await db.latest_chat_session("t1") == "sess-1"
