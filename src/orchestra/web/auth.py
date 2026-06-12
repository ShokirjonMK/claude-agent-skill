"""Autentifikatsiya: parol hash (bcrypt), JWT, joriy foydalanuvchi.

JWT imzolangan session cookie'da saqlanadi. `get_current_user` so'rovdan cookie'ni
o'qib, foydalanuvchini bazadan yuklaydi.
"""

from __future__ import annotations

import datetime as dt

import bcrypt
import jwt
from fastapi import Request

from ..models import User

COOKIE_NAME = "session"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


def create_token(user_id: str, secret: str, *, hours: int = 24) -> str:
    payload = {
        "sub": user_id,
        "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> dict | None:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


async def ensure_bootstrap_admin(db, settings) -> None:
    """Foydalanuvchilar yo'q bo'lsa va .env'da BOOTSTRAP_ADMIN_PASS berilgan bo'lsa,
    birinchi admin'ni yaratadi (Docker/birinchi ishga tushish uchun)."""
    from ..models import Role, User

    existing = await db.list_users()
    if existing or not settings.bootstrap_admin_pass:
        return
    await db.save_user(
        User(
            username=settings.bootstrap_admin_user,
            password_hash=hash_password(settings.bootstrap_admin_pass),
            role=Role.ADMIN,
        )
    )
    await db.log_audit(
        actor_type="system", actor_id=None, action="user.bootstrap",
        target=settings.bootstrap_admin_user,
    )


async def get_current_user(request: Request) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    secret = request.app.state.settings.web_jwt_secret
    data = decode_token(token, secret)
    if not data:
        return None
    user = await request.app.state.db.get_user(data.get("sub"))
    if not user or not user.is_active:
        return None
    return user
