"""Real-vaqt SSE oqimi — bazadagi event'larni poll qiladi.

DB-poll (in-process hub o'rniga) — shu sababli orchestrator/bot va web alohida
jarayonlarda (Docker) ishlaganda ham dashboard yangilanadi (umumiy baza orqali).
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ...models import Role
from ...rbac import require_role

router = APIRouter()


@router.get("/events/stream")
async def events_stream(request: Request, user=Depends(require_role(Role.VIEWER))):
    db = request.app.state.db

    async def gen():
        last = await db.last_event_id()
        yield ": connected\n\n"
        while True:
            if await request.is_disconnected():
                break
            new = await db.events_since(last, limit=100)
            for e in new:
                last = max(last, e["id"])
                payload = {
                    "type": "event",
                    "role": e.get("status"),
                    "agent_id": e.get("agent_id"),
                    "status": e.get("message"),
                    "task_id": e.get("task_id"),
                }
                yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream")
