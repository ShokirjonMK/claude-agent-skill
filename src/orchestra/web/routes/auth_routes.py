"""Login / logout."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..auth import COOKIE_NAME, create_token, verify_password

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, error: str | None = None):
    return request.app.state.templates.TemplateResponse(
        "login.html", {"request": request, "error": error, "user": None}
    )


@router.post("/login")
async def login_submit(
    request: Request, username: str = Form(...), password: str = Form(...)
):
    db = request.app.state.db
    user = await db.get_user_by_username(username)
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        await db.log_audit(
            actor_type="system", actor_id=None, action="user.login.failed",
            target=username,
        )
        return RedirectResponse("/login?error=1", status_code=303)

    token = create_token(user.id, request.app.state.settings.web_jwt_secret)
    await db.touch_login(user.id)
    await db.log_audit(actor_type="user", actor_id=user.id, action="user.login", target=user.id)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax")
    return resp


@router.get("/logout")
async def logout(request: Request):
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp
