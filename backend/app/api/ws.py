from __future__ import annotations

from fastapi import APIRouter, WebSocket

from app.core.auth import require_ws_token
from app.ws.events import hub

router = APIRouter()


@router.websocket("/ws/events")
async def events(ws: WebSocket) -> None:
    try:
        await require_ws_token(ws)
    except Exception:
        await ws.close(code=4401)
        return
    await hub.serve(ws)
