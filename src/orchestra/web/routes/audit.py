"""Audit timeline — kim/qachon/nima qildi."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...models import Role
from ...rbac import require_role

router = APIRouter()


@router.get("/audit")
async def audit_view(
    request: Request, q: str | None = None, user=Depends(require_role(Role.VIEWER))
):
    db = request.app.state.db
    entries = await db.list_audit(limit=300, action_like=q)
    return request.app.state.templates.TemplateResponse(
        "audit.html", {"request": request, "user": user, "entries": entries, "q": q or ""}
    )
