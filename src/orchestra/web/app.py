"""FastAPI ilova fabrikasi.

`create_app(db, store, settings, hub)` — ulangan DB va SecretStore'ni qabul qiladi
(CLI yoki test inject qiladi). 401 (auth yo'q) → /login redirect; 403 → forbidden.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..config import Settings
from ..db import AsyncDB
from ..secrets import SecretStore

HERE = Path(__file__).parent


def create_app(
    db: AsyncDB,
    store: SecretStore,
    settings: Settings,
    *,
    hub=None,
    connect_on_startup: bool = False,
) -> FastAPI:
    app = FastAPI(title="Orchestra Admin", docs_url=None, redoc_url=None)
    app.state.db = db
    app.state.store = store
    app.state.settings = settings
    app.state.hub = hub
    app.state.templates = Jinja2Templates(directory=str(HERE / "templates"))

    static_dir = HERE / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    from .routes import (
        audit,
        auth_routes,
        chat,
        dashboard,
        secrets as secrets_routes,
        servers,
        ssh,
        stream,
        tasks,
        users,
    )

    for mod in (
        auth_routes, dashboard, tasks, audit, stream, chat,
        ssh, servers, secrets_routes, users,
    ):
        app.include_router(mod.router)

    if connect_on_startup:
        @app.on_event("startup")
        async def _connect_db():
            from .auth import ensure_bootstrap_admin

            await db.connect()
            await db.initdb()
            await ensure_bootstrap_admin(db, settings)

        @app.on_event("shutdown")
        async def _close_db():
            await db.close()

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exc(request, exc: StarletteHTTPException):
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=307)
        if exc.status_code == 403:
            return PlainTextResponse("Ruxsat yo'q (403)", status_code=403)
        if exc.status_code == 404:
            return PlainTextResponse("Topilmadi (404)", status_code=404)
        return PlainTextResponse(str(exc.detail), status_code=exc.status_code)

    return app
