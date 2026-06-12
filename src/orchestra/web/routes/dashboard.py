"""Dashboard — faol vazifalar/agentlar + real-vaqt oqim (SSE)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...models import Role
from ...rbac import require_role

router = APIRouter()


@router.get("/")
async def dashboard(request: Request, user=Depends(require_role(Role.VIEWER))):
    db = request.app.state.db
    tasks = await db.recent_tasks(limit=15)
    runs = await db.active_agent_runs()
    events = await db.list_events(limit=20)
    return request.app.state.templates.TemplateResponse(request, "dashboard.html",
        {"request": request, "user": user, "tasks": tasks, "runs": runs, "events": events},
    )
