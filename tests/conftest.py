"""Umumiy test fixture'lari.

SDK va tashqi xizmatlarsiz ishlaydi: baza SQLite (vaqtinchalik fayl), secrets esa
test Fernet kaliti bilan. asyncpg/claude_agent_sdk/asyncssh o'rnatilmagan bo'lsa ham
bu testlar o'tadi (ular faqat SQLite + mock ishlatadi).
"""

from __future__ import annotations

import pytest_asyncio

from orchestra.config import Settings
from orchestra.db import SQLiteDB
from orchestra.secrets import SecretStore, generate_key


@pytest_asyncio.fixture
async def db(tmp_path):
    """Toza, migratsiya qilingan SQLite bazasi (har test uchun yangi fayl)."""
    database = SQLiteDB(str(tmp_path / "test.db"))
    await database.connect()
    await database.initdb()
    yield database
    await database.close()


@pytest_asyncio.fixture
def settings():
    """Test Settings — Fernet kaliti generatsiya qilingan."""
    return Settings(
        DB_DSN="sqlite:///:memory:",
        SECRET_ENC_KEY=generate_key(),
        WEB_JWT_SECRET="test-jwt-secret",
        BOOTSTRAP_ADMIN_USER="admin",
        BOOTSTRAP_ADMIN_PASS="admin123",
        ANTHROPIC_API_KEY="env-fallback-key",
    )


@pytest_asyncio.fixture
async def store(db, settings):
    """Test bazasiga ulangan SecretStore."""
    return SecretStore(db, settings)
