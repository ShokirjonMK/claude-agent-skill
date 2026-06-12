"""Interaktiv web chat — agent bilan suhbat (operator+).

GET /chat[?task=<id>]  — chat sahifasi (vazifa tanlash + tarix).
WS  /chat/{task}/ws    — jonli suhbat (task='general' → vazifasiz erkin suhbat).
Kontekst SDK resume orqali saqlanadi (ChatService).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, WebSocket

from ...chat import ChatService
from ...models import Role
from ...rbac import require_role
from ..auth import get_current_user

router = APIRouter()


@router.get("/chat")
async def chat_page(
    request: Request, task: str | None = None, user=Depends(require_role(Role.OPERATOR))
):
    db = request.app.state.db
    tasks = await db.recent_tasks(limit=30)
    selected = await db.get_task(task) if task else None
    history = await db.list_chat_messages(task, limit=200) if task else []
    return request.app.state.templates.TemplateResponse(request, "chat.html",
        {
            "request": request, "user": user, "tasks": tasks,
            "selected": selected, "history": history,
            "channel": task or "general",
        },
    )


@router.websocket("/chat/{task}/ws")
async def chat_ws(websocket: WebSocket, task: str):
    await websocket.accept()
    user = await get_current_user(websocket)  # type: ignore[arg-type]
    if user is None or not user.role.allows(Role.OPERATOR):
        await websocket.close(code=4403)
        return

    db = websocket.app.state.db
    store = websocket.app.state.store
    svc = ChatService(db, store)
    task_id = None if task in ("general", "", "none") else task

    try:
        while True:
            text = await websocket.receive_text()
            if not text.strip():
                continue
            try:
                reply = await svc.send(
                    task_id=task_id, user_text=text, channel="web", user_id=user.id
                )
            except Exception as exc:  # noqa: BLE001
                reply = f"[xato] {exc}"
            await websocket.send_text(reply)
    except Exception:
        # ulanish uzildi
        pass
