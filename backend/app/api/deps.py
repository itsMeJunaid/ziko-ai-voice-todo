"""Per-request wiring: session scope → settings → datetime service → task service."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.auth import require_token
from app.core.clock import Clock
from app.database.engine import session_scope
from app.schemas.settings import AppSettings
from app.services.datetime_service import DateTimeService
from app.services.settings_service import CredentialStore, SettingsService
from app.services.task_service import TaskService


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def get_credentials(request: Request) -> CredentialStore:
    return request.app.state.credentials


def get_session() -> Iterator[Session]:
    with session_scope() as s:
        yield s


@dataclass
class Ctx:
    session: Session
    clock: Clock
    settings: AppSettings
    settings_service: SettingsService
    dts: DateTimeService
    tasks: TaskService


def build_ctx(session: Session, clock: Clock) -> Ctx:
    """Shared by the HTTP API and the AI tools so both go through the same services and validation."""
    ss = SettingsService(session, clock)
    settings = ss.get()
    dts = DateTimeService(clock, settings.tasks.timezone)
    return Ctx(session, clock, settings, ss, dts, TaskService(session, dts, settings.tasks))


def get_ctx(
    _: None = Depends(require_token),
    session: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
) -> Ctx:
    return build_ctx(session, clock)
