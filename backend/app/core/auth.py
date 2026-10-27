"""Bearer-token guard. The frontend receives the token from Tauri at launch (PRD §11.1)."""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_config

_bearer = HTTPBearer(auto_error=False)


def _check(token: str | None) -> None:
    expected = get_config().token
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid token")


async def require_token(_: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    _check(creds.credentials if creds else None)


async def require_ws_token(ws: WebSocket) -> None:
    # Browsers cannot set headers on WebSocket upgrades → token via query string (loopback only).
    _check(ws.query_params.get("token"))
