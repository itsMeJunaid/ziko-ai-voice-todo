"""In-process event hub → WebSocket fan-out (PRD §8.4). Event types:
task.changed, reminder.due, reminder.changed, voice.state, voice.transcript, backend.status."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)


class EventHub:
    def __init__(self) -> None:
        self._clients: dict[WebSocket, asyncio.Queue[dict[str, Any]]] = {}

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def publish(self, type_: str, payload: dict[str, Any] | None = None) -> None:
        event = {"type": type_, "payload": payload or {}}
        for ws, q in list(self._clients.items()):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("dropping event for slow client")
                self._clients.pop(ws, None)

    async def serve(self, ws: WebSocket) -> None:
        await ws.accept()
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._clients[ws] = q
        try:
            await ws.send_json({"type": "backend.status", "payload": {"status": "connected"}})
            while True:
                event = await q.get()
                await ws.send_json(event)
        except Exception:
            pass
        finally:
            self._clients.pop(ws, None)


hub = EventHub()
