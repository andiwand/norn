"""A small in-process event bus. The web UI listens to it over a WebSocket (/api/events)."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[dict[str, Any]]] = set()

    def publish(self, type_: str, data: dict[str, Any] | None = None) -> None:
        event = {"type": type_, "time": time.time(), "data": data or {}}
        for queue in list(self._queues):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        # A slow client drops events instead of growing memory without bound.
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._queues.add(queue)
        try:
            yield queue
        finally:
            self._queues.discard(queue)
