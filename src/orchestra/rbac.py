"""RBAC — rollarni tekshiruvchi FastAPI dependency'lari.

Rollar tartibi (models.Role): viewer < operator < admin. Har web endpoint
`Depends(require_role(...))` bilan himoyalanadi va joriy foydalanuvchini qaytaradi.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from .models import Role, User


def ensure(user: User | None, min_role: Role | str) -> User:
    """Toza tekshiruv: user yo'q → 401; rol yetarli emas → 403."""
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth kerak")
    if not user.role.allows(min_role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ruxsat yo'q")
    return user


def require_role(min_role: Role | str):
    """`Depends(require_role(Role.ADMIN))` — joriy foydalanuvchini qaytaradi yoki rad etadi."""

    async def _dep(request: Request) -> User:
        from .web.auth import get_current_user  # circular importdan saqlanish uchun lazy

        user = await get_current_user(request)
        return ensure(user, min_role)

    return _dep
