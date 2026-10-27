from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Priority = Literal["low", "medium", "high"]
Status = Literal["pending", "completed", "archived"]
Source = Literal["voice", "text", "ui"]
View = Literal["today", "upcoming", "overdue", "pending", "completed", "archived", "all"]


def _strip(v: str | None) -> str | None:
    return v.strip() if isinstance(v, str) else v


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    priority: Priority | None = None  # None → settings default
    due_at: datetime | None = None  # naive → interpreted in the user's timezone
    reminder_at: datetime | None = None
    reminder_enabled: bool = False  # True + due_at + no reminder_at → due_at − default offset
    source: Source = "ui"

    _strip_title = field_validator("title", "description", mode="before")(_strip)


class TaskUpdate(BaseModel):
    """PATCH semantics: only fields present in the request body are applied (null clears nullable fields)."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    priority: Priority | None = None
    status: Literal["pending", "completed"] | None = None  # archive via its own endpoint
    due_at: datetime | None = None
    reminder_at: datetime | None = None

    _strip_title = field_validator("title", "description", mode="before")(_strip)


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str | None
    status: Status
    priority: Priority
    due_at: datetime | None
    reminder_at: datetime | None
    timezone: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    archived_at: datetime | None
    source: Source
    is_overdue: bool = False


class TaskList(BaseModel):
    items: list[TaskOut]
    view: View
    count: int


class DailySummary(BaseModel):
    date: str  # local ISO date
    timezone: str
    now_local: datetime
    today: list[TaskOut]
    overdue: list[TaskOut]
    upcoming_reminders: list[TaskOut]
    completed_today: int
