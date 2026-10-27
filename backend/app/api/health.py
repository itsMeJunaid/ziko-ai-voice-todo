from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import text

from app import __version__
from app.database.engine import get_engine
from app.schemas.common import Health

router = APIRouter()


@router.get("/health", response_model=Health)
async def health(request: Request) -> Health:
    try:
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
        db = "ok"
    except Exception as e:  # surfaced to Tauri's startup wait (PRD §8.5)
        db = f"error: {type(e).__name__}"
    return Health(
        status="ok" if db == "ok" else "degraded",
        version=__version__,
        db=db,
        credential_store=request.app.state.credentials.backend,
    )
