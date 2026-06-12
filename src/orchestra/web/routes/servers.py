"""SSH serverlar CRUD (admin)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from ...models import Role, Server
from ...rbac import require_role

router = APIRouter()


@router.get("/servers")
async def list_servers(request: Request, user=Depends(require_role(Role.ADMIN))):
    servers = await request.app.state.db.list_servers()
    return request.app.state.templates.TemplateResponse(
        "servers.html", {"request": request, "user": user, "servers": servers}
    )


@router.post("/servers")
async def add_server(
    request: Request,
    name: str = Form(...),
    host: str = Form(...),
    port: int = Form(22),
    username: str = Form(...),
    auth_method: str = Form("password"),
    secret_value: str = Form(""),
    user=Depends(require_role(Role.ADMIN)),
):
    db = request.app.state.db
    store = request.app.state.store
    secret_ref = None
    if secret_value:
        secret_ref = f"SSH_{name.upper().replace(' ', '_')}"
        await store.set_secret(secret_ref, secret_value, by_user=user.id, is_secret=True)
    server = Server(
        name=name, host=host, port=int(port), username=username,
        auth_method=auth_method, secret_ref=secret_ref, created_by=user.id,
    )
    await db.save_server(server)
    await db.log_audit(
        actor_type="user", actor_id=user.id, action="server.created", target=server.id
    )
    return RedirectResponse("/servers", status_code=303)


@router.post("/servers/{server_id}/delete")
async def delete_server(server_id: str, request: Request, user=Depends(require_role(Role.ADMIN))):
    await request.app.state.db.delete_server(server_id)
    await request.app.state.db.log_audit(
        actor_type="user", actor_id=user.id, action="server.deleted", target=server_id
    )
    return RedirectResponse("/servers", status_code=303)
