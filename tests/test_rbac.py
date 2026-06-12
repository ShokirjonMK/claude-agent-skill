"""RBAC pure-mantiq testlari (ensure, Role.allows)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from orchestra.models import Role, User
from orchestra.rbac import ensure


def test_role_ordering():
    assert Role.ADMIN.allows(Role.VIEWER)
    assert Role.ADMIN.allows(Role.OPERATOR)
    assert Role.OPERATOR.allows(Role.VIEWER)
    assert not Role.VIEWER.allows(Role.OPERATOR)
    assert not Role.OPERATOR.allows(Role.ADMIN)


def test_ensure_no_user_401():
    with pytest.raises(HTTPException) as ei:
        ensure(None, Role.VIEWER)
    assert ei.value.status_code == 401


def test_ensure_insufficient_403():
    u = User(username="v", role=Role.VIEWER)
    with pytest.raises(HTTPException) as ei:
        ensure(u, Role.ADMIN)
    assert ei.value.status_code == 403


def test_ensure_ok_returns_user():
    u = User(username="a", role=Role.ADMIN)
    assert ensure(u, Role.OPERATOR) is u


def test_allows_accepts_string():
    assert Role.ADMIN.allows("viewer")
    assert not Role.VIEWER.allows("admin")
