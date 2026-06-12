"""Dinamik secrets boshqaruvi (admin)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from ...models import Role
from ...rbac import require_role

router = APIRouter()


@router.get("/secrets")
async def list_secrets(request: Request, user=Depends(require_role(Role.ADMIN))):
    store = request.app.state.store
    items = await store.list_for_ui()
    return request.app.state.templates.TemplateResponse(request, "secrets.html",
        {
            "request": request, "user": user, "items": items,
            "enc_ok": store.encryption_available,
        },
    )


@router.post("/secrets")
async def set_secret(
    request: Request,
    key: str = Form(...),
    value: str = Form(...),
    is_secret: str = Form("on"),
    description: str = Form(""),
    user=Depends(require_role(Role.ADMIN)),
):
    store = request.app.state.store
    await store.set_secret(
        key.strip(), value, by_user=user.id,
        description=description or None, is_secret=(is_secret == "on"),
    )
    await request.app.state.db.log_audit(
        actor_type="user", actor_id=user.id, action="secret.updated", target=key
    )
    return RedirectResponse("/secrets", status_code=303)


@router.post("/secrets/{key}/delete")
async def delete_secret(key: str, request: Request, user=Depends(require_role(Role.ADMIN))):
    await request.app.state.store.delete_secret(key)
    await request.app.state.db.log_audit(
        actor_type="user", actor_id=user.id, action="secret.deleted", target=key
    )
    return RedirectResponse("/secrets", status_code=303)
