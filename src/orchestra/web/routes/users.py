"""Foydalanuvchilar + rollar CRUD (admin)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from ...models import Role, User
from ...rbac import require_role
from ..auth import hash_password

router = APIRouter()


@router.get("/users")
async def list_users(request: Request, user=Depends(require_role(Role.ADMIN))):
    users = await request.app.state.db.list_users()
    return request.app.state.templates.TemplateResponse(request, "users.html", {"request": request, "user": user, "users": users}
    )


@router.post("/users")
async def add_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("viewer"),
    user=Depends(require_role(Role.ADMIN)),
):
    db = request.app.state.db
    if await db.get_user_by_username(username):
        return RedirectResponse("/users", status_code=303)
    new = User(
        username=username.strip(),
        password_hash=hash_password(password),
        role=Role(role),
    )
    await db.save_user(new)
    await db.log_audit(
        actor_type="user", actor_id=user.id, action="user.created",
        target=new.id, details={"role": role},
    )
    return RedirectResponse("/users", status_code=303)


@router.post("/users/{user_id}/delete")
async def delete_user(user_id: str, request: Request, user=Depends(require_role(Role.ADMIN))):
    if user_id != user.id:  # o'zini o'chirmaslik
        await request.app.state.db.delete_user(user_id)
        await request.app.state.db.log_audit(
            actor_type="user", actor_id=user.id, action="user.deleted", target=user_id
        )
    return RedirectResponse("/users", status_code=303)
