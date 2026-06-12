"""CLI va bootstrap smoke-testlari."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from orchestra import cli
from orchestra.config import Settings
from orchestra.db import SQLiteDB
from orchestra.secrets import SecretStore, generate_key
from orchestra.web.app import create_app


def _settings(tmp_path, **kw):
    return Settings(
        DB_DSN=f"sqlite:///{tmp_path / 'cli.db'}",
        SECRET_ENC_KEY=generate_key(),
        WEB_JWT_SECRET="t",
        **kw,
    )


def test_submit_and_status(tmp_path, monkeypatch, capsys):
    s = _settings(tmp_path)
    monkeypatch.setattr(cli, "get_settings", lambda: s)

    asyncio.run(cli.cmd_initdb())
    asyncio.run(cli.cmd_submit("CLI orqali vazifa"))
    out = capsys.readouterr().out
    assert "Vazifa qo'shildi" in out
    task_id = out.split("Vazifa qo'shildi:")[1].strip().splitlines()[0]

    asyncio.run(cli.cmd_status(task_id[:8]))
    out2 = capsys.readouterr().out
    assert "PENDING" in out2


def test_createadmin(tmp_path, monkeypatch, capsys):
    s = _settings(tmp_path)
    monkeypatch.setattr(cli, "get_settings", lambda: s)
    asyncio.run(cli.cmd_initdb())
    asyncio.run(cli.cmd_createadmin("boss", "pw12345"))
    assert "Admin yaratildi" in capsys.readouterr().out


def test_web_connect_on_startup_seeds_admin(tmp_path):
    """create_app(connect_on_startup=True) + bootstrap admin → login ishlaydi."""
    settings = _settings(tmp_path, BOOTSTRAP_ADMIN_USER="root", BOOTSTRAP_ADMIN_PASS="rootpass")
    db = SQLiteDB(str(tmp_path / "web2.db"))
    store = SecretStore(db, settings)
    app = create_app(db, store, settings, connect_on_startup=True)
    with TestClient(app, base_url="https://testserver") as client:
        r = client.post("/login", data={"username": "root", "password": "rootpass"})
        assert r.status_code == 200
        assert "Dashboard" in r.text
