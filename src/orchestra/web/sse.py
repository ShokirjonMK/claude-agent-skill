"""Real-vaqt event hub (SSE uchun).

In-process pub/sub: orchestrator/reporter `publish(event)` chaqiradi, dashboard
SSE endpoint'i `subscribe()` orqali oqimni oladi. `publish` Broadcaster shakliga
mos (async).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import AsyncIterator


class EventHub:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    async def publish(self, event: dict) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    @contextlib.contextmanager
    def subscribe(self):
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        try:
            yield q
        finally:
            self._subscribers.discard(q)

    async def stream(self) -> AsyncIterator[str]:
        """SSE matn oqimi (`data: {...}\\n\\n`)."""
        with self.subscribe() as q:
            # Ulanish ochilganini bildiruvchi boshlang'ich ping.
            yield ": connected\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
