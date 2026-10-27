from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, TypeDecorator
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator[datetime]):
    """Store timezone-aware datetimes as naive UTC in SQLite; always return aware UTC (PRD §5.2)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:  # type: ignore[override]
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime passed to UTCDateTime; convert with datetime_service first")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:  # type: ignore[override]
        return None if value is None else value.replace(tzinfo=UTC)
