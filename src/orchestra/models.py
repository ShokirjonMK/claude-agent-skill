"""Ma'lumotlar modeli: enum'lar va dataclass'lar.

Yagona haqiqat manbai — baza; bu dataclass'lar shunchaki yozuvlarning typed ko'rinishi.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def new_id() -> str:
    """uuid4 string identifikatori."""
    return str(uuid.uuid4())


def utcnow() -> str:
    """ISO-8601 UTC vaqt (baza TEXT ustunlarida portativ)."""
    return datetime.now(timezone.utc).isoformat()


def short_agent_id(role: str) -> str:
    """`executor-ab12cd` ko'rinishidagi agent ishga tushish ID si."""
    return f"{role}-{uuid.uuid4().hex[:6]}"


def new_code(prefix: str = "T") -> str:
    """Vazifa uchun qisqa, inson-o'qiy tracking kodi: `T-ab123` yoki `prod-ab123`."""
    safe = "".join(ch for ch in (prefix or "T") if ch.isalnum())[:8] or "T"
    return f"{safe.upper()}-{uuid.uuid4().hex[:5]}"


class TaskStatus(str, Enum):
    """Vazifa hayot tsikli. v1'dagi o'lik TESTING holati OLIB TASHLANGAN —
    Reviewer testni REVIEWING ichida bajaradi."""

    PENDING = "PENDING"
    ANALYZING = "ANALYZING"
    PLANNED = "PLANNED"
    EXECUTING = "EXECUTING"
    REVIEWING = "REVIEWING"
    DONE = "DONE"
    FAILED = "FAILED"


# Holatlar yakuniy (terminal) hisoblanadi → resume ularni qayta ishga tushirmaydi.
TERMINAL_STATUSES = {TaskStatus.DONE, TaskStatus.FAILED}


class Role(str, Enum):
    """RBAC rollari, tartiblangan: viewer < operator < admin."""

    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"

    @property
    def level(self) -> int:
        return {"viewer": 0, "operator": 1, "admin": 2}[self.value]

    def allows(self, required: "Role | str") -> bool:
        """Joriy rol `required` ruxsat darajasini qoplaydimi."""
        req = Role(required) if not isinstance(required, Role) else required
        return self.level >= req.level


@dataclass
class Task:
    id: str = field(default_factory=new_id)
    kind: str = "root"  # 'root' | 'subtask'
    title: str = ""
    description: str = ""
    code: str | None = None  # qisqa tracking kodi (T-ab123)
    server_id: str | None = None  # qaysi serverga tegishli (NULL = umumiy)
    parent_id: str | None = None
    strategy: str | None = None
    deps: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: str | None = None
    attempts: int = 0
    agent_id: str | None = None
    session_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class AgentRun:
    id: str
    task_id: str
    role: str
    model: str
    status: str = "running"
    started_at: str | None = None
    finished_at: str | None = None


@dataclass
class User:
    id: str = field(default_factory=new_id)
    username: str = ""
    password_hash: str = ""
    role: Role = Role.VIEWER
    is_active: bool = True
    last_login: str | None = None
    created_at: str | None = None


@dataclass
class Server:
    id: str = field(default_factory=new_id)
    name: str = ""
    host: str = ""
    port: int = 22
    username: str = ""
    auth_method: str = "password"  # 'password' | 'key'
    secret_ref: str | None = None  # secrets.key ga ishora
    tg_chat_id: str | None = None  # shu server botining chat id si
    tg_token_ref: str | None = None  # shu server boti tokeni (secrets.key)
    created_by: str | None = None
    created_at: str | None = None


@dataclass
class Event:
    id: int
    task_id: str | None
    agent_id: str | None
    status: str
    message: str
    created_at: str


@dataclass
class ChatMessage:
    id: int | None
    task_id: str | None
    chat_session_id: str | None
    channel: str  # 'telegram' | 'web'
    direction: str  # 'in' | 'out'
    role: str  # 'user' | 'agent'
    content: str
    user_id: str | None = None
    created_at: str | None = None


@dataclass
class AuditEntry:
    id: int | None
    actor_type: str  # 'user' | 'agent' | 'system'
    actor_id: str | None
    action: str
    target: str | None
    details: str | None  # JSON
    created_at: str | None = None
