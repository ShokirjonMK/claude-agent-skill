"""Web admin-panel testlari (FastAPI TestClient): login, RBAC, secrets, SSE hub."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from orchestra.config import Settings
from orchestra.db import SQLiteDB
from orchestra.models import Role, User
from orchestra.secrets import SecretStore, generate_key
from orchestra.web.app import create_app
from orchestra.web.auth import hash_password
from orchestra.web.sse import EventHub


@pytest.fixture
def web(tmp_path):
    settings = Settings(SECRET_ENC_KEY=generate_key(), WEB_JWT_SECRET="test-secret")
    db = SQLiteDB(str(tmp_path / "web.db"))
    store = SecretStore(db, settings)
    app = create_app(db, store, settings, hub=EventHub())

    @app.on_event("startup")
    async def _start():
        await db.connect()
        await db.initdb()
        await db.save_user(
            User(username="admin", password_hash=hash_password("admin123"), role=Role.ADMIN)
        )
        await db.save_user(
            User(username="viewer", password_hash=hash_password("view123"), role=Role.VIEWER)
        )

    @app.on_event("shutdown")
    async def _stop():
        await db.close()

    # base_url https — Secure cookie test muhitida ham yuborilishi uchun.
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


def test_unauthenticated_redirects_to_login(web):
    r = web.get("/", follow_redirects=False)
    assert r.status_code in (302, 303, 307)
    assert "/login" in r.headers["location"]


def test_login_success_and_dashboard(web):
    r = login(web, "admin", "admin123")
    assert r.status_code == 200
    assert "Dashboard" in r.text


def test_login_wrong_password(web):
    r = login(web, "admin", "nope")
    # noto'g'ri → /login?error=1 ga qaytadi
    assert "Login yoki parol noto'g'ri" in r.text or "error=1" in str(r.url)


def test_viewer_forbidden_on_admin_pages(web):
    login(web, "viewer", "view123")
    for path in ("/secrets", "/servers", "/users", "/ssh"):
        r = web.get(path)
        assert r.status_code == 403, path


def test_admin_can_access_admin_pages(web):
    login(web, "admin", "admin123")
    for path in ("/secrets", "/servers", "/users", "/ssh", "/telegram"):
        assert web.get(path).status_code == 200, path


def test_viewer_forbidden_on_telegram(web):
    login(web, "viewer", "view123")
    assert web.get("/telegram").status_code == 403


def test_admin_sets_and_sees_secret(web):
    login(web, "admin", "admin123")
    web.post(
        "/secrets",
        data={"key": "MAX_PARALLEL", "value": "8", "is_secret": "off", "description": "test"},
    )
    page = web.get("/secrets").text
    assert "MAX_PARALLEL" in page and "8" in page


def test_viewer_cannot_create_task(web):
    login(web, "viewer", "view123")
    r = web.post("/tasks", data={"description": "x"}, follow_redirects=False)
    assert r.status_code == 403


def test_admin_creates_task_and_lists(web):
    login(web, "admin", "admin123")
    web.post("/tasks", data={"description": "Web orqali vazifa"})
    assert "Web orqali vazifa"[:20] in web.get("/tasks").text


def test_audit_records_login(web):
    login(web, "admin", "admin123")
    assert "user.login" in web.get("/audit").text


def test_chat_page_requires_operator(web):
    login(web, "viewer", "view123")
    assert web.get("/chat").status_code == 403


def test_admin_can_open_chat(web):
    login(web, "admin", "admin123")
    r = web.get("/chat")
    assert r.status_code == 200
    assert "suhbat" in r.text.lower()


def test_logout_clears_session(web):
    login(web, "admin", "admin123")
    web.get("/logout")
    r = web.get("/", follow_redirects=False)
    assert "/login" in r.headers["location"]


# ── EventHub (SSE) unit ───────────────────────────────────────────────────────
async def test_event_hub_publish_subscribe():
    hub = EventHub()
    with hub.subscribe() as q:
        await hub.publish({"type": "report", "status": "ok"})
        evt = await asyncio.wait_for(q.get(), timeout=1)
        assert evt["status"] == "ok"
