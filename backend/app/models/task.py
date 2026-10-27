from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, UTCDateTime


class TaskStatus(enum.StrEnum):
    pending = "pending"
    completed = "completed"
    archived = "archived"


class TaskPriority(enum.StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class TaskSource(enum.StrEnum):
    voice = "voice"
    text = "text"
    ui = "ui"


def _enum_check(col: str, e: type[enum.StrEnum]) -> CheckConstraint:
    values = ", ".join(f"'{v.value}'" for v in e)
    return CheckConstraint(f"{col} IN ({values})", name=f"ck_tasks_{col}")


class Task(Base):
    """PRD §5.2 task data model. Timestamps are UTC; `timezone` is the IANA zone used to interpret them."""

    __tablename__ = "tasks"
    __table_args__ = (
        _enum_check("status", TaskStatus),
        _enum_check("priority", TaskPriority),
        _enum_check("source", TaskSource),
        CheckConstraint("length(title) BETWEEN 1 AND 200", name="ck_tasks_title_len"),
        CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)",
            name="ck_tasks_completed_consistency",
        ),
        CheckConstraint(
            "(status = 'archived') = (archived_at IS NOT NULL)",
            name="ck_tasks_archived_consistency",
        ),
        Index("ix_tasks_status_due", "status", "due_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=TaskStatus.pending.value)
    priority: Mapped[str] = mapped_column(String(8), nullable=False, default=TaskPriority.medium.value)
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reminder_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(8), nullable=False, default=TaskSource.ui.value)

    reminders: Mapped[list[Reminder]] = relationship(  # noqa: F821
        "Reminder", back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )
