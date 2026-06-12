"""Secrets testlari: Fernet shifr/deshifr va layered resolver (DB > .env > default)."""

from __future__ import annotations

import pytest

from orchestra.config import Settings
from orchestra.secrets import SecretStore, _mask, generate_key


async def test_encrypt_roundtrip(store):
    await store.set_secret("ANTHROPIC_API_KEY", "sk-ant-secret-123", by_user="u1")
    assert await store.get_secret("ANTHROPIC_API_KEY") == "sk-ant-secret-123"


async def test_stored_value_is_encrypted_at_rest(store, db):
    await store.set_secret("ANTHROPIC_API_KEY", "sk-ant-plaintext", by_user="u1")
    row = await db.get_secret_row("ANTHROPIC_API_KEY")
    assert "sk-ant-plaintext" not in (row["value_encrypted"] or "")


async def test_resolver_db_over_env(store):
    # .env fallback "env-fallback-key" (conftest settings).
    assert await store.get_config("ANTHROPIC_API_KEY") == "env-fallback-key"
    # DB qiymati ustun bo'lishi kerak.
    await store.set_secret("ANTHROPIC_API_KEY", "db-wins", by_user="u1")
    assert await store.get_config("ANTHROPIC_API_KEY") == "db-wins"


async def test_resolver_falls_back_to_default(store):
    assert await store.get_config("NOT_SET", default="fallback") == "fallback"


async def test_get_int_float(store):
    await store.set_secret("MAX_PARALLEL", "7", by_user="u1", is_secret=False)
    assert await store.get_int("MAX_PARALLEL", 5) == 7
    await store.set_secret("POLL_INTERVAL", "1.5", by_user="u1", is_secret=False)
    assert await store.get_float("POLL_INTERVAL", 2.0) == 1.5


async def test_list_for_ui_masks_sensitive(store):
    await store.set_secret("ANTHROPIC_API_KEY", "sk-ant-supersecretvalue", by_user="u1")
    await store.set_secret("MAX_PARALLEL", "9", by_user="u1", is_secret=False)
    ui = {r["key"]: r for r in await store.list_for_ui()}
    assert ui["ANTHROPIC_API_KEY"]["value_display"] != "sk-ant-supersecretvalue"
    assert "…" in ui["ANTHROPIC_API_KEY"]["value_display"]
    assert ui["MAX_PARALLEL"]["value_display"] == "9"  # secret emas → ochiq


async def test_no_enc_key_disables_encryption(db):
    s = Settings(SECRET_ENC_KEY="", ANTHROPIC_API_KEY="env-only")
    store = SecretStore(db, s)
    assert store.encryption_available is False
    # .env fallback baribir ishlaydi.
    assert await store.get_config("ANTHROPIC_API_KEY") == "env-only"


def test_mask_helper():
    assert _mask("") == ""
    assert _mask("abcd") == "••••"
    assert _mask("0123456789") == "0123…6789"
