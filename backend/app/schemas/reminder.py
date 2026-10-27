from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ReminderStateName = Literal[
    "scheduled", "delivering", "delivered", "snoozed", "dismissed", "cancelled", "missed", "failed"
]


class ReminderOut(BaseModel):
    id: str
    task_id: str
    task_title: str
    task_due_at: datetime | None
    fire_at: datetime
    state: ReminderStateName
    delivered_at: datetime | None
    missed: bool  # delivered late because the app was off or the computer slept (PRD §7.4)


class ReminderList(BaseModel):
    """`attention`: fired and not yet snoozed/dismissed. `upcoming`: still scheduled, soonest first."""

    attention: list[ReminderOut]
    upcoming: list[ReminderOut]


class SnoozeIn(BaseModel):
    minutes: int | None = Field(default=None, ge=1, le=240)  # None → settings.tasks.snooze_minutes
