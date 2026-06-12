"""Vazifalar — ro'yxat, yaratish, batafsil, qayta navbatga qo'yish."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from ...models import Role, Task, TaskStatus, new_code
from ...rbac import require_role

router = APIRouter()


@router.get("/tasks")
async def list_tasks(request: Request, user=Depends(require_role(Role.VIEWER))):
    db = request.app.state.db
    tasks = await db.recent_tasks(limit=50)
    servers = await db.list_servers()
    smap = {s.id: s.name for s in servers}
    return request.app.state.templates.TemplateResponse(
        request, "tasks.html",
        {"request": request, "user": user, "tasks": tasks, "servers": servers, "smap": smap},
    )


@router.post("/tasks")
async def create_task(
    request: Request,
    description: str = Form(...),
    user=Depends(require_role(Role.OPERATOR)),
):
    db = request.app.state.db
    server_id = (await request.form()).get("server_id") or None
    t = Task(
        kind="root", title=description[:80], description=description,
        status=TaskStatus.PENDING, code=new_code(), server_id=server_id,
    )
    await db.save_task(t)
    await db.log_audit(
        actor_type="user", actor_id=user.id, action="task.created",
        target=t.id, details={"channel": "web", "code": t.code},
    )
    return RedirectResponse("/tasks", status_code=303)


@router.get("/tasks/{task_id}")
async def task_detail(task_id: str, request: Request, user=Depends(require_role(Role.VIEWER))):
    db = request.app.state.db
    task = await db.get_task(task_id)
    if not task:
        return RedirectResponse("/tasks", status_code=303)
    subtasks = await db.list_subtasks(task_id)
    events = await db.list_events(task_id, limit=100)
    chat = await db.list_chat_messages(task_id, limit=100)
    return request.app.state.templates.TemplateResponse(request, "task_detail.html",
        {
            "request": request, "user": user, "task": task,
            "subtasks": subtasks, "events": events, "chat": chat,
        },
    )


@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str, request: Request, user=Depends(require_role(Role.OPERATOR))):
    db = request.app.state.db
    task = await db.get_task(task_id)
    if task:
        # FAILED subtask'larni PENDING'ga qaytarib, root'ni PLANNED qilamiz →
        # orchestrator idempotent davom etadi (qayta rejalashtirmaydi).
        for st in await db.list_subtasks(task_id):
            if st.status is TaskStatus.FAILED:
                await db.update_status(st.id, TaskStatus.PENDING)
        await db.update_status(task_id, TaskStatus.PLANNED if await db.has_subtasks(task_id) else TaskStatus.PENDING)
        await db.log_audit(
            actor_type="user", actor_id=user.id, action="task.retry", target=task_id
        )
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)
