"""Task CRUD + views (PRD §5.1). Every mutation is validated here, committed by the caller's session scope,
and announced on the event hub so the UI updates immediately (PRD §3.2)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import Ambiguous, NotFound, Validation
from app.core.logging import redact_title
from app.models.task import Task, TaskStatus
from app.schemas.settings import TaskSettings
from app.schemas.task import TaskCreate, TaskOut, TaskUpdate, View
from app.services.datetime_service import DateTimeService
from app.services.reminder_service import ReminderService
from app.ws.events import hub

log = logging.getLogger(__name__)


class TaskService:
    def __init__(self, session: Session, dts: DateTimeService, task_settings: TaskSettings) -> None:
        self.session = session
        self.dts = dts
        self.settings = task_settings
        self.reminders = ReminderService(session, dts)

    # ------------------------------------------------------------------ helpers
    def to_out(self, t: Task) -> TaskOut:
        now = self.dts.now_utc()
        out = TaskOut.model_validate(t)
        out.is_overdue = t.status == TaskStatus.pending and t.due_at is not None and t.due_at < now
        return out

    def _get(self, task_id: str) -> Task:
        t = self.session.get(Task, task_id)
        if t is None:
            raise NotFound(f"Task {task_id} not found")
        return t

    def _validate_times(self, due_at: datetime | None, reminder_at: datetime | None) -> None:
        now = self.dts.now_utc()
        if reminder_at is not None:
            if due_at is not None and reminder_at > due_at:
                raise Validation("Reminder time must not be after the due time")
            if reminder_at < now - timedelta(minutes=1):
                raise Validation("Reminder time is in the past")

    def _derive_reminder(self, data: TaskCreate, due_at: datetime | None) -> datetime | None:
        if data.reminder_at is not None:
            return self.dts.to_utc(data.reminder_at)
        if data.reminder_enabled and due_at is not None:
            return due_at - timedelta(minutes=self.settings.default_reminder_offset_min)
        return None

    def _touch(self, t: Task) -> None:
        t.updated_at = self.dts.now_utc()

    def _emit(self, action: str, t: Task) -> None:
        hub.publish("task.changed", {"action": action, "task": self.to_out(t).model_dump(mode="json")})

    # ------------------------------------------------------------------ CRUD
    def create(self, data: TaskCreate) -> Task:
        now = self.dts.now_utc()
        due_at = self.dts.to_utc(data.due_at)
        reminder_at = self._derive_reminder(data, due_at)
        self._validate_times(due_at, reminder_at)
        t = Task(
            title=data.title,
            description=data.description or None,
            priority=data.priority or self.settings.default_priority,
            status=TaskStatus.pending.value,
            due_at=due_at,
            reminder_at=reminder_at,
            timezone=self.dts.zone_name,
            created_at=now,
            updated_at=now,
            source=data.source,
        )
        self.session.add(t)
        self.session.flush()
        self.reminders.sync(t, reminder_changed=True)
        log.info("task created id=%s title=%s", t.id, redact_title(t.title))
        self._emit("created", t)
        return t

    def get(self, task_id: str) -> Task:
        return self._get(task_id)

    def update(self, task_id: str, patch: TaskUpdate) -> Task:
        t = self._get(task_id)
        if t.status == TaskStatus.archived:
            raise Validation("Archived tasks cannot be edited; restore it first")
        fields = patch.model_dump(exclude_unset=True)
        if not fields:
            return t
        due_at = self.dts.to_utc(fields["due_at"]) if "due_at" in fields else t.due_at
        reminder_at = self.dts.to_utc(fields["reminder_at"]) if "reminder_at" in fields else t.reminder_at
        if "due_at" in fields and "reminder_at" not in fields and due_at is None:
            reminder_at = None  # no deadline → no deadline-relative reminder
        self._validate_times(due_at, reminder_at)
        for k in ("title", "description", "priority"):
            if k in fields:
                setattr(t, k, fields[k] or (None if k == "description" else getattr(t, k)))
        reminder_changed = reminder_at != t.reminder_at
        t.due_at, t.reminder_at = due_at, reminder_at
        if "status" in fields and fields["status"] != t.status:
            reminder_changed = True
            if fields["status"] == "completed":
                self._mark_completed(t)
            else:
                t.status, t.completed_at = TaskStatus.pending.value, None
        self._touch(t)
        self.session.flush()
        self.reminders.sync(t, reminder_changed=reminder_changed)
        self._emit("updated", t)
        return t

    def _mark_completed(self, t: Task) -> None:
        t.status = TaskStatus.completed.value
        t.completed_at = self.dts.now_utc()

    def complete(self, task_id: str) -> Task:
        t = self._get(task_id)
        if t.status == TaskStatus.archived:
            raise Validation("Archived tasks cannot be completed")
        if t.status != TaskStatus.completed:
            self._mark_completed(t)
            self._touch(t)
            self.session.flush()
            self.reminders.sync(t, reminder_changed=False)  # completed → future reminders cancelled
            self._emit("completed", t)
        return t

    def reopen(self, task_id: str) -> Task:
        t = self._get(task_id)
        if t.status == TaskStatus.archived:
            t.archived_at = None
        t.status, t.completed_at = TaskStatus.pending.value, None
        self._touch(t)
        self.session.flush()
        self.reminders.sync(t, reminder_changed=True)  # comes back only if it can still fire on time
        self._emit("updated", t)
        return t

    def archive(self, task_id: str) -> Task:
        """Soft delete (PRD §5.1): recoverable via reopen()."""
        t = self._get(task_id)
        if t.status != TaskStatus.archived:
            t.status, t.archived_at, t.completed_at = (
                TaskStatus.archived.value,
                self.dts.now_utc(),
                None,
            )
            self._touch(t)
            self.session.flush()
            self.reminders.sync(t, reminder_changed=False)
            self._emit("archived", t)
        return t

    def delete_all(self) -> int:
        n = self.session.query(Task).delete()
        self.session.flush()
        hub.publish("task.changed", {"action": "deleted_all"})
        return n

    # ------------------------------------------------------------------ queries
    def list(self, view: View = "today", q: str | None = None, limit: int = 200) -> list[Task]:
        now = self.dts.now_utc()
        day_start, day_end = self.dts.local_day_window()
        stmt = select(Task)
        pending = Task.status == TaskStatus.pending.value
        if view == "today":
            # pending & (undated | due before end of today, which includes overdue)
            stmt = stmt.where(pending, or_(Task.due_at.is_(None), Task.due_at < day_end))
        elif view == "upcoming":
            stmt = stmt.where(pending, Task.due_at >= day_end)
        elif view == "overdue":
            stmt = stmt.where(pending, Task.due_at < now)
        elif view == "pending":
            stmt = stmt.where(pending)
        elif view == "completed":
            cutoff = now - timedelta(days=self.settings.completed_retention_days)
            stmt = stmt.where(Task.status == TaskStatus.completed.value, Task.completed_at >= cutoff)
        elif view == "archived":
            stmt = stmt.where(Task.status == TaskStatus.archived.value)
        if q:
            stmt = stmt.where(func.lower(Task.title).contains(q.lower()))
        order = [Task.due_at.is_(None), Task.due_at.asc()]
        if view == "completed":
            order = [Task.completed_at.desc()]
        stmt = stmt.order_by(*order, Task.created_at.asc()).limit(limit)
        return list(self.session.scalars(stmt))

    def find_by_title(self, query: str, *, include_completed: bool = False) -> list[Task]:
        """Lookup for voice commands: exact (case-insensitive) match wins, else substring matches."""
        qn = query.strip().lower()
        if not qn:
            return []
        statuses = [TaskStatus.pending.value] + ([TaskStatus.completed.value] if include_completed else [])
        rows = list(self.session.scalars(select(Task).where(Task.status.in_(statuses))))
        exact = [t for t in rows if t.title.lower() == qn]
        if exact:
            return exact
        return [t for t in rows if qn in t.title.lower() or t.title.lower() in qn]

    def resolve_one(self, query: str) -> Task:
        """For tools: exactly one match or raise NotFound / Ambiguous (PRD §5.1 clarification rule)."""
        matches = self.find_by_title(query)
        if not matches:
            raise NotFound(f"No task matches '{query}'")
        if len(matches) > 1:
            raise Ambiguous(
                f"{len(matches)} tasks match '{query}'",
                details={
                    "candidates": [
                        {
                            "id": t.id,
                            "title": t.title,
                            "due_at": t.due_at.isoformat() if t.due_at else None,
                        }
                        for t in matches
                    ]
                },
            )
        return matches[0]

    def completed_today_count(self) -> int:
        start, end = self.dts.local_day_window()
        return (
            self.session.scalar(
                select(func.count())
                .select_from(Task)
                .where(
                    Task.status == TaskStatus.completed.value,
                    Task.completed_at >= start,
                    Task.completed_at < end,
                )
            )
            or 0
        )
