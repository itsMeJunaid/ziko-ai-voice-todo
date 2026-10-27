"""Injectable clock so services and the scheduler are testable (PRD §16 unit tests)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now_utc(self) -> datetime: ...


class SystemClock:
    def now_utc(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FakeClock start must be timezone-aware")
        self._now = start.astimezone(UTC)

    def now_utc(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> None:
        from datetime import timedelta

        self._now += timedelta(**kwargs)

    def set(self, dt: datetime) -> None:
        self._now = dt.astimezone(UTC)
