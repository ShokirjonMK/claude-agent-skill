"""Ma'lumotlar bazasi qatlami — yagona haqiqat manbai.

`AsyncDB` abstrakt interfeys barcha domen metodlarini `?` placeholder'li SQL bilan
yozadi; konkret backend'lar (`SQLiteDB`, `PostgresDB`) faqat past darajadagi
primitivlarni (_execute/_fetchone/_fetchall) va placeholder dialektini ta'minlaydi.
Shu tarzda Postgres ↔ SQLite almashtirish portativ bo'ladi (NFR: portativlik).
"""

from __future__ import annotations

import abc
import json
from typing import Any

from .models import (
    AgentRun,
    Role,
    Server,
    Task,
    TaskStatus,
    User,
    new_id,
    short_agent_id,
    utcnow,
)

# ── Schema (dialekt-neutral; {serial} PK per-dialect almashtiriladi) ──────────
_TABLES: dict[str, str] = {
    "tasks": """
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            parent_id TEXT,
            kind TEXT NOT NULL,
            title TEXT,
            description TEXT,
            strategy TEXT,
            deps TEXT,
            status TEXT NOT NULL,
            result TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            agent_id TEXT,
            session_id TEXT,
            created_at TEXT,
            updated_at TEXT
        )""",
    "agent_runs": """
        CREATE TABLE IF NOT EXISTS agent_runs (
            id TEXT PRIMARY KEY,
            task_id TEXT,
            role TEXT,
            model TEXT,
            status TEXT,
            started_at TEXT,
            finished_at TEXT
        )""",
    "events": """
        CREATE TABLE IF NOT EXISTS events (
            id {serial},
            task_id TEXT,
            agent_id TEXT,
            status TEXT,
            message TEXT,
            created_at TEXT
        )""",
    "users": """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            last_login TEXT,
            created_at TEXT
        )""",
    "secrets": """
        CREATE TABLE IF NOT EXISTS secrets (
            key TEXT PRIMARY KEY,
            value_encrypted TEXT,
            description TEXT,
            is_secret INTEGER NOT NULL DEFAULT 1,
            updated_by TEXT,
            updated_at TEXT
        )""",
    "servers": """
        CREATE TABLE IF NOT EXISTS servers (
            id TEXT PRIMARY KEY,
            name TEXT,
            host TEXT,
            port INTEGER NOT NULL DEFAULT 22,
            username TEXT,
            auth_method TEXT,
            secret_ref TEXT,
            created_by TEXT,
            created_at TEXT
        )""",
    "ssh_commands": """
        CREATE TABLE IF NOT EXISTS ssh_commands (
            id {serial},
            server_id TEXT,
            user_id TEXT,
            command TEXT,
            output TEXT,
            exit_code INTEGER,
            duration_ms INTEGER,
            created_at TEXT
        )""",
    "chat_messages": """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id {serial},
            task_id TEXT,
            chat_session_id TEXT,
            channel TEXT,
            direction TEXT,
            role TEXT,
            content TEXT,
            user_id TEXT,
            created_at TEXT
        )""",
    "audit_log": """
        CREATE TABLE IF NOT EXISTS audit_log (
            id {serial},
            actor_type TEXT,
            actor_id TEXT,
            action TEXT,
            target TEXT,
            details TEXT,
            created_at TEXT
        )""",
}


def _task_from_row(row: dict[str, Any]) -> Task:
    return Task(
        id=row["id"],
        parent_id=row["parent_id"],
        kind=row["kind"],
        title=row["title"] or "",
        description=row["description"] or "",
        strategy=row["strategy"],
        deps=json.loads(row["deps"]) if row["deps"] else [],
        status=TaskStatus(row["status"]),
        result=row["result"],
        attempts=row["attempts"] or 0,
        agent_id=row["agent_id"],
        session_id=row["session_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _user_from_row(row: dict[str, Any]) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        password_hash=row["password_hash"],
        role=Role(row["role"]),
        is_active=bool(row["is_active"]),
        last_login=row["last_login"],
        created_at=row["created_at"],
    )


def _server_from_row(row: dict[str, Any]) -> Server:
    return Server(
        id=row["id"],
        name=row["name"],
        host=row["host"],
        port=row["port"],
        username=row["username"],
        auth_method=row["auth_method"],
        secret_ref=row["secret_ref"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


class AsyncDB(abc.ABC):
    """Domen metodlari `?` placeholder'da yoziladi; backend dialektni hal qiladi."""

    dialect: str = "sqlite"

    # ── Primitivlar (backend implement qiladi) ───────────────────────────────
    @abc.abstractmethod
    async def connect(self) -> None: ...

    @abc.abstractmethod
    async def close(self) -> None: ...

    @abc.abstractmethod
    async def _execute(self, sql: str, params: tuple = ()) -> None: ...

    @abc.abstractmethod
    async def _fetchone(self, sql: str, params: tuple = ()) -> dict[str, Any] | None: ...

    @abc.abstractmethod
    async def _fetchall(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]: ...

    @abc.abstractmethod
    async def _create_tables(self) -> None: ...

    async def initdb(self) -> None:
        await self._create_tables()

    # ── tasks ────────────────────────────────────────────────────────────────
    async def save_task(self, task: Task) -> None:
        now = utcnow()
        await self._execute(
            """INSERT INTO tasks
               (id, parent_id, kind, title, description, strategy, deps, status,
                result, attempts, agent_id, session_id, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task.id, task.parent_id, task.kind, task.title, task.description,
                task.strategy, json.dumps(task.deps), task.status.value, task.result,
                task.attempts, task.agent_id, task.session_id,
                task.created_at or now, now,
            ),
        )

    async def get_task(self, task_id: str) -> Task | None:
        row = await self._fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return _task_from_row(row) if row else None

    async def save_subtasks(self, parent_id: str, subtasks: list[dict]) -> list[Task]:
        """Planner natijasidagi subtask'larni yozadi. Planner-local id'lar (s1, s2)
        haqiqiy UUID'ga moslanadi va `deps` UUID ko'rinishida saqlanadi — shunda resume
        paytida bog'liqlik to'g'ri tiklanadi. Idempotent emas — chaqiruvchi `has_subtasks`
        bilan tekshirib chaqiradi."""
        # 1-bosqich: barcha subtask'larga UUID beriladi, local→uuid xaritasi tuziladi.
        prepared: list[tuple[Task, list[str]]] = []
        local_to_uuid: dict[str, str] = {}
        for st in subtasks:
            t = Task(
                id=new_id(),
                parent_id=parent_id,
                kind="subtask",
                title=st.get("title", st.get("id", "subtask")),
                description=st.get("title", ""),
                deps=[],
                status=TaskStatus.PENDING,
            )
            local_id = st.get("id")
            if local_id:
                local_to_uuid[local_id] = t.id
            prepared.append((t, st.get("deps", []) or []))

        # 2-bosqich: deps local id'larni UUID'ga moslab yozish.
        created: list[Task] = []
        for t, local_deps in prepared:
            t.deps = [local_to_uuid.get(d, d) for d in local_deps]
            await self.save_task(t)
            created.append(t)
        return created

    async def list_subtasks(self, parent_id: str) -> list[Task]:
        rows = await self._fetchall(
            "SELECT * FROM tasks WHERE parent_id = ? ORDER BY created_at", (parent_id,)
        )
        return [_task_from_row(r) for r in rows]

    async def has_subtasks(self, parent_id: str) -> bool:
        """Resume idempotentligi uchun: root allaqachon rejalashtirilganmi."""
        row = await self._fetchone(
            "SELECT COUNT(*) AS n FROM tasks WHERE parent_id = ?", (parent_id,)
        )
        return bool(row and row["n"] > 0)

    async def next_pending_root(self) -> Task | None:
        """Tugamagan (DONE/FAILED emas) eng eski root vazifa."""
        row = await self._fetchone(
            """SELECT * FROM tasks
               WHERE kind = 'root' AND status NOT IN ('DONE','FAILED')
               ORDER BY created_at LIMIT 1"""
        )
        return _task_from_row(row) if row else None

    async def recent_tasks(self, limit: int = 10, kind: str | None = "root") -> list[Task]:
        if kind:
            rows = await self._fetchall(
                "SELECT * FROM tasks WHERE kind = ? ORDER BY created_at DESC LIMIT ?",
                (kind, limit),
            )
        else:
            rows = await self._fetchall(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        return [_task_from_row(r) for r in rows]

    async def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        sets = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status.value, utcnow()]
        if agent_id is not None:
            sets.append("agent_id = ?")
            params.append(agent_id)
        if session_id is not None:
            sets.append("session_id = ?")
            params.append(session_id)
        params.append(task_id)
        await self._execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", tuple(params))

    async def set_result(self, task_id: str, result: str) -> None:
        await self._execute(
            "UPDATE tasks SET result = ?, updated_at = ? WHERE id = ?",
            (result, utcnow(), task_id),
        )

    async def set_strategy(self, task_id: str, strategy: str) -> None:
        await self._execute(
            "UPDATE tasks SET strategy = ?, updated_at = ? WHERE id = ?",
            (strategy, utcnow(), task_id),
        )

    async def increment_attempts(self, task_id: str) -> int:
        await self._execute(
            "UPDATE tasks SET attempts = attempts + 1, updated_at = ? WHERE id = ?",
            (utcnow(), task_id),
        )
        row = await self._fetchone("SELECT attempts FROM tasks WHERE id = ?", (task_id,))
        return int(row["attempts"]) if row else 0

    # ── agent_runs ─────────────────────────────────────────────────────────
    async def start_agent_run(self, task_id: str, role: str, model: str) -> AgentRun:
        run = AgentRun(
            id=short_agent_id(role), task_id=task_id, role=role, model=model,
            status="running", started_at=utcnow(),
        )
        await self._execute(
            """INSERT INTO agent_runs (id, task_id, role, model, status, started_at, finished_at)
               VALUES (?,?,?,?,?,?,?)""",
            (run.id, run.task_id, run.role, run.model, run.status, run.started_at, None),
        )
        return run

    async def finish_agent_run(self, run_id: str, status: str = "done") -> None:
        await self._execute(
            "UPDATE agent_runs SET status = ?, finished_at = ? WHERE id = ?",
            (status, utcnow(), run_id),
        )

    async def active_agent_runs(self) -> list[dict[str, Any]]:
        return await self._fetchall(
            "SELECT * FROM agent_runs WHERE status = 'running' ORDER BY started_at DESC"
        )

    # ── events ───────────────────────────────────────────────────────────────
    async def log_event(
        self, task_id: str | None, agent_id: str | None, status: str, message: str
    ) -> None:
        await self._execute(
            "INSERT INTO events (task_id, agent_id, status, message, created_at) VALUES (?,?,?,?,?)",
            (task_id, agent_id, status, message, utcnow()),
        )

    async def list_events(self, task_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if task_id:
            return await self._fetchall(
                "SELECT * FROM events WHERE task_id = ? ORDER BY id DESC LIMIT ?",
                (task_id, limit),
            )
        return await self._fetchall("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))

    async def events_since(self, after_id: int, limit: int = 50) -> list[dict[str, Any]]:
        """`after_id` dan keyingi yangi event'lar (SSE cross-process poll uchun)."""
        return await self._fetchall(
            "SELECT * FROM events WHERE id > ? ORDER BY id ASC LIMIT ?", (after_id, limit)
        )

    async def last_event_id(self) -> int:
        row = await self._fetchone("SELECT MAX(id) AS m FROM events")
        return int(row["m"]) if row and row["m"] is not None else 0

    # ── users ────────────────────────────────────────────────────────────────
    async def save_user(self, user: User) -> None:
        await self._execute(
            """INSERT INTO users (id, username, password_hash, role, is_active, last_login, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                user.id, user.username, user.password_hash, user.role.value,
                1 if user.is_active else 0, user.last_login, user.created_at or utcnow(),
            ),
        )

    async def update_user(self, user: User) -> None:
        await self._execute(
            """UPDATE users SET password_hash = ?, role = ?, is_active = ? WHERE id = ?""",
            (user.password_hash, user.role.value, 1 if user.is_active else 0, user.id),
        )

    async def get_user_by_username(self, username: str) -> User | None:
        row = await self._fetchone("SELECT * FROM users WHERE username = ?", (username,))
        return _user_from_row(row) if row else None

    async def get_user(self, user_id: str) -> User | None:
        row = await self._fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
        return _user_from_row(row) if row else None

    async def list_users(self) -> list[User]:
        rows = await self._fetchall("SELECT * FROM users ORDER BY created_at")
        return [_user_from_row(r) for r in rows]

    async def touch_login(self, user_id: str) -> None:
        await self._execute(
            "UPDATE users SET last_login = ? WHERE id = ?", (utcnow(), user_id)
        )

    async def delete_user(self, user_id: str) -> None:
        await self._execute("DELETE FROM users WHERE id = ?", (user_id,))

    # ── secrets ──────────────────────────────────────────────────────────────
    async def get_secret_row(self, key: str) -> dict[str, Any] | None:
        return await self._fetchone("SELECT * FROM secrets WHERE key = ?", (key,))

    async def set_secret_row(
        self, key: str, value_encrypted: str, *, description: str | None,
        is_secret: bool, updated_by: str | None,
    ) -> None:
        existing = await self.get_secret_row(key)
        if existing:
            await self._execute(
                """UPDATE secrets SET value_encrypted = ?, description = ?, is_secret = ?,
                   updated_by = ?, updated_at = ? WHERE key = ?""",
                (value_encrypted, description, 1 if is_secret else 0, updated_by, utcnow(), key),
            )
        else:
            await self._execute(
                """INSERT INTO secrets (key, value_encrypted, description, is_secret, updated_by, updated_at)
                   VALUES (?,?,?,?,?,?)""",
                (key, value_encrypted, description, 1 if is_secret else 0, updated_by, utcnow()),
            )

    async def list_secrets(self) -> list[dict[str, Any]]:
        return await self._fetchall("SELECT * FROM secrets ORDER BY key")

    async def delete_secret(self, key: str) -> None:
        await self._execute("DELETE FROM secrets WHERE key = ?", (key,))

    # ── servers ──────────────────────────────────────────────────────────────
    async def save_server(self, server: Server) -> None:
        await self._execute(
            """INSERT INTO servers (id, name, host, port, username, auth_method, secret_ref, created_by, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                server.id, server.name, server.host, server.port, server.username,
                server.auth_method, server.secret_ref, server.created_by,
                server.created_at or utcnow(),
            ),
        )

    async def get_server(self, server_id: str) -> Server | None:
        row = await self._fetchone("SELECT * FROM servers WHERE id = ?", (server_id,))
        return _server_from_row(row) if row else None

    async def list_servers(self) -> list[Server]:
        rows = await self._fetchall("SELECT * FROM servers ORDER BY created_at")
        return [_server_from_row(r) for r in rows]

    async def delete_server(self, server_id: str) -> None:
        await self._execute("DELETE FROM servers WHERE id = ?", (server_id,))

    # ── ssh_commands (audit) ─────────────────────────────────────────────────
    async def log_ssh_command(
        self, server_id: str, user_id: str | None, command: str, output: str,
        exit_code: int | None, duration_ms: int,
    ) -> None:
        await self._execute(
            """INSERT INTO ssh_commands (server_id, user_id, command, output, exit_code, duration_ms, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (server_id, user_id, command, output, exit_code, duration_ms, utcnow()),
        )

    async def list_ssh_commands(self, server_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if server_id:
            return await self._fetchall(
                "SELECT * FROM ssh_commands WHERE server_id = ? ORDER BY id DESC LIMIT ?",
                (server_id, limit),
            )
        return await self._fetchall("SELECT * FROM ssh_commands ORDER BY id DESC LIMIT ?", (limit,))

    # ── chat_messages ────────────────────────────────────────────────────────
    async def save_chat_message(
        self, *, task_id: str | None, chat_session_id: str | None, channel: str,
        direction: str, role: str, content: str, user_id: str | None = None,
    ) -> None:
        await self._execute(
            """INSERT INTO chat_messages
               (task_id, chat_session_id, channel, direction, role, content, user_id, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (task_id, chat_session_id, channel, direction, role, content, user_id, utcnow()),
        )

    async def list_chat_messages(self, task_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if task_id:
            return await self._fetchall(
                "SELECT * FROM chat_messages WHERE task_id = ? ORDER BY id LIMIT ?",
                (task_id, limit),
            )
        return await self._fetchall("SELECT * FROM chat_messages ORDER BY id DESC LIMIT ?", (limit,))

    async def latest_chat_session(self, task_id: str) -> str | None:
        row = await self._fetchone(
            """SELECT chat_session_id FROM chat_messages
               WHERE task_id = ? AND chat_session_id IS NOT NULL
               ORDER BY id DESC LIMIT 1""",
            (task_id,),
        )
        return row["chat_session_id"] if row else None

    # ── audit_log (append-only) ──────────────────────────────────────────────
    async def log_audit(
        self, *, actor_type: str, actor_id: str | None, action: str,
        target: str | None = None, details: dict | None = None,
    ) -> None:
        await self._execute(
            """INSERT INTO audit_log (actor_type, actor_id, action, target, details, created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                actor_type, actor_id, action, target,
                json.dumps(details) if details else None, utcnow(),
            ),
        )

    async def list_audit(self, limit: int = 200, action_like: str | None = None) -> list[dict[str, Any]]:
        if action_like:
            return await self._fetchall(
                "SELECT * FROM audit_log WHERE action LIKE ? ORDER BY id DESC LIMIT ?",
                (f"%{action_like}%", limit),
            )
        return await self._fetchall("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))


# ── SQLite backend ───────────────────────────────────────────────────────────
class SQLiteDB(AsyncDB):
    dialect = "sqlite"

    def __init__(self, path: str):
        self._path = path
        self._conn: Any = None

    async def connect(self) -> None:
        import aiosqlite

        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _execute(self, sql: str, params: tuple = ()) -> None:
        await self._conn.execute(sql, params)
        await self._conn.commit()

    async def _fetchone(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        cur = await self._conn.execute(sql, params)
        row = await cur.fetchone()
        await cur.close()
        return dict(row) if row else None

    async def _fetchall(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        cur = await self._conn.execute(sql, params)
        rows = await cur.fetchall()
        await cur.close()
        return [dict(r) for r in rows]

    async def _create_tables(self) -> None:
        for ddl in _TABLES.values():
            await self._conn.execute(ddl.format(serial="INTEGER PRIMARY KEY AUTOINCREMENT"))
        await self._conn.commit()


# ── PostgreSQL backend ───────────────────────────────────────────────────────
class PostgresDB(AsyncDB):
    dialect = "postgres"

    def __init__(self, dsn: str):
        # asyncpg "postgresql://" sxemasini kutadi.
        self._dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
        self._pool: Any = None

    async def connect(self) -> None:
        import asyncpg

        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=10)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    @staticmethod
    def _convert(sql: str) -> str:
        """`?` placeholder'larni $1,$2,... ga aylantiradi."""
        out: list[str] = []
        n = 0
        for ch in sql:
            if ch == "?":
                n += 1
                out.append(f"${n}")
            else:
                out.append(ch)
        return "".join(out)

    async def _execute(self, sql: str, params: tuple = ()) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(self._convert(sql), *params)

    async def _fetchone(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(self._convert(sql), *params)
            return dict(row) if row else None

    async def _fetchall(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(self._convert(sql), *params)
            return [dict(r) for r in rows]

    async def _create_tables(self) -> None:
        async with self._pool.acquire() as conn:
            for ddl in _TABLES.values():
                await conn.execute(ddl.format(serial="BIGSERIAL PRIMARY KEY"))


# ── Factory ──────────────────────────────────────────────────────────────────
def make_db(dsn: str) -> AsyncDB:
    """DSN sxemasiga qarab mos backend qaytaradi."""
    if dsn.startswith("sqlite"):
        # sqlite:///path  |  sqlite:///:memory:
        if ":///" in dsn:
            path = dsn.split(":///", 1)[1]
        else:
            path = dsn.split("://", 1)[1]
        return SQLiteDB(path or ":memory:")
    if dsn.startswith("postgres"):
        return PostgresDB(dsn)
    raise ValueError(f"Noma'lum DB DSN sxemasi: {dsn!r}")
