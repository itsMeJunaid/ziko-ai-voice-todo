from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, UTCDateTime


class ReminderState(enum.StrEnum):
    """PRD §7.4 lifecycle. `delivering` is the atomic claim state used by the scheduler (Phase 3)."""

    scheduled = "scheduled"
    delivering = "delivering"
    delivered = "delivered"
    snoozed = "snoozed"
    dismissed = "dismissed"
    cancelled = "cancelled"
    missed = "missed"
    failed = "failed"


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (
        CheckConstraint(
            "state IN ('scheduled','delivering','delivered','snoozed',"
            "'dismissed','cancelled','missed','failed')",
            name="ck_reminders_state",
        ),
        Index("ix_reminders_state_fire", "state", "fire_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    fire_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default=ReminderState.scheduled.value)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    task: Mapped[Task] = relationship("Task", back_populates="reminders")  # noqa: F821
