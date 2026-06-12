"""SSH boshqaruv sahifasi (admin): komanda yuborish + tarix + WebSocket terminal."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, WebSocket
from fastapi.responses import RedirectResponse

from ...models import Role
from ...rbac import require_role
from ...ssh import SSHManager
from ..auth import get_current_user

router = APIRouter()


@router.get("/ssh")
async def ssh_page(request: Request, server: str | None = None, user=Depends(require_role(Role.ADMIN))):
    db = request.app.state.db
    servers = await db.list_servers()
    selected = await db.get_server(server) if server else None
    history = await db.list_ssh_commands(server, limit=50) if server else []
    return request.app.state.templates.TemplateResponse(
        "ssh.html",
        {
            "request": request, "user": user, "servers": servers,
            "selected": selected, "history": history, "last": None,
        },
    )


@router.post("/ssh/{server_id}/run")
async def ssh_run(
    server_id: str,
    request: Request,
    command: str = Form(...),
    user=Depends(require_role(Role.ADMIN)),
):
    db = request.app.state.db
    server = await db.get_server(server_id)
    if not server:
        return RedirectResponse("/ssh", status_code=303)
    mgr = SSHManager(db, request.app.state.store)
    result = await mgr.run_command(server, command, user_id=user.id)
    servers = await db.list_servers()
    history = await db.list_ssh_commands(server_id, limit=50)
    return request.app.state.templates.TemplateResponse(
        "ssh.html",
        {
            "request": request, "user": user, "servers": servers,
            "selected": server, "history": history, "last": result,
        },
    )


@router.websocket("/ssh/{server_id}/terminal")
async def ssh_terminal(websocket: WebSocket, server_id: str):
    await websocket.accept()
    user = await get_current_user(websocket)  # type: ignore[arg-type]
    if user is None or not user.role.allows(Role.ADMIN):
        await websocket.close(code=4403)
        return
    db = websocket.app.state.db
    server = await db.get_server(server_id)
    if not server:
        await websocket.close(code=4404)
        return
    mgr = SSHManager(db, websocket.app.state.store)
    try:
        await mgr.interactive_shell(server, websocket, user_id=user.id)
    except Exception as exc:  # noqa: BLE001
        try:
            await websocket.send_text(f"[terminal xato] {exc}")
        finally:
            await websocket.close()
