"""Authoritative time handling (PRD §5.3): system clock + configured IANA timezone.

All storage is UTC. Naive datetimes coming from the UI or the model are interpreted in the user's zone.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import tzlocal

from app.core.clock import Clock
from app.core.errors import Validation


def system_timezone_name() -> str:
    try:
        return tzlocal.get_localzone_name() or "UTC"
    except Exception:
        return "UTC"


def resolve_zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or system_timezone_name())
    except ZoneInfoNotFoundError as e:
        raise Validation(f"Unknown timezone: {name}") from e


class DateTimeService:
    def __init__(self, clock: Clock, timezone: str | None) -> None:
        self.clock = clock
        self.zone = resolve_zone(timezone)

    @property
    def zone_name(self) -> str:
        return str(self.zone.key)

    def now_utc(self) -> datetime:
        return self.clock.now_utc()

    def now_local(self) -> datetime:
        return self.now_utc().astimezone(self.zone)

    def to_utc(self, dt: datetime | None) -> datetime | None:
        """Naive → assume user zone; aware → convert. Always returns aware UTC."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self.zone)
        return dt.astimezone(UTC)

    def to_local(self, dt: datetime | None) -> datetime | None:
        return None if dt is None else dt.astimezone(self.zone)

    def local_day_window(self, offset_days: int = 0) -> tuple[datetime, datetime]:
        """[start, end) of a local calendar day expressed in UTC — DST-safe via zoneinfo."""
        day = (self.now_local() + timedelta(days=offset_days)).date()
        start = datetime.combine(day, time.min, tzinfo=self.zone)
        end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=self.zone)
        return start.astimezone(UTC), end.astimezone(UTC)

    def local_date_iso(self) -> str:
        return self.now_local().date().isoformat()
