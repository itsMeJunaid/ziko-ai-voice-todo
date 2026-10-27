from __future__ import annotations

from pydantic import BaseModel


class Health(BaseModel):
    status: str
    version: str
    db: str
    credential_store: str


class Ok(BaseModel):
    ok: bool = True
