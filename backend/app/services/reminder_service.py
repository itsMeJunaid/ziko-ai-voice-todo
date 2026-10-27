"""Reminder rows behind a task's `reminder_at` (PRD §7). The task field is what the user edits; this
service keeps one `scheduled` row in step with it and owns snooze / dismiss. Delivery is the scheduler's."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import NotFound, Validation
from app.models.reminder import Reminder, ReminderState
from app.models.task import Task, TaskStatus
from app.schemas.reminder import ReminderList, ReminderOut
from app.services.datetime_service import DateTimeService
from app.ws.events import hub

log = logging.getLogger(__name__)

# Fired reminders the user has not acted on yet; they stay on the card until snoozed or dismissed.
ATTENTION = (ReminderState.delivered.value, ReminderState.missed.value)


def reminder_out(r: Reminder) -> ReminderOut:
    return ReminderOut(
        id=r.id,
        task_id=r.task_id,
        task_title=r.task.title,
        task_due_at=r.task.due_at,
        fire_at=r.fire_at,
        state=r.state,
        delivered_at=r.delivered_at,
        missed=r.state == ReminderState.missed,
    )


class ReminderService:
    def __init__(self, session: Session, dts: DateTimeService) -> None:
        self.session = session
        self.dts = dts

    def _emit(self, task_id: str) -> None:
        hub.publish("reminder.changed", {"task_id": task_id})

    def _close_open(self, task_id: str) -> int:
        """Not-yet-fired rows → cancelled; fired-but-unacknowledged rows → dismissed. Returns rows changed."""
        now, changed = self.dts.now_utc(), 0
        for states, to in (
            ((ReminderState.scheduled.value,), ReminderState.cancelled),
            (ATTENTION, ReminderState.dismissed),
        ):
            res = self.session.execute(
                update(Reminder)
                .where(Reminder.task_id == task_id, Reminder.state.in_(states))
                .values(state=to.value, updated_at=now)
            )
            changed += res.rowcount or 0
        return changed

    def sync(self, task: Task, *, reminder_changed: bool) -> None:
        """Call after any task mutation. Not pending → cancel. New/changed reminder time → reschedule.
        An untouched reminder is left alone so an active snooze survives unrelated edits."""
        if task.status != TaskStatus.pending:
            if self._close_open(task.id):
                self._emit(task.id)
            return
        if not reminder_changed:
            return
        self._close_open(task.id)
        if task.reminder_at is not None and task.reminder_at > self.dts.now_utc():
            now = self.dts.now_utc()
            self.session.add(
                Reminder(task_id=task.id, fire_at=task.reminder_at, created_at=now, updated_at=now)
            )
            log.info("reminder scheduled task=%s fire_at=%s", task.id, task.reminder_at.isoformat())
        self.session.flush()
        self._emit(task.id)

    # ------------------------------------------------------------------ user actions
    def _get(self, reminder_id: str) -> Reminder:
        r = self.session.get(Reminder, reminder_id)
        if r is None:
            raise NotFound(f"Reminder {reminder_id} not found")
        return r

    def snooze(self, reminder_id: str, minutes: int) -> Reminder:
        r = self._get(reminder_id)
        if r.state not in ATTENTION:
            raise Validation("Only a reminder that has fired can be snoozed")
        if r.task.status != TaskStatus.pending:
            raise Validation("The task is no longer pending")
        now = self.dts.now_utc()
        r.state, r.updated_at = ReminderState.snoozed.value, now
        again = Reminder(
            task_id=r.task_id, fire_at=now + timedelta(minutes=minutes), created_at=now, updated_at=now
        )
        self.session.add(again)
        self.session.flush()
        self._emit(r.task_id)
        return again

    def dismiss(self, reminder_id: str) -> Reminder:
        """Acknowledge a fired reminder, or skip one that has not fired yet."""
        r = self._get(reminder_id)
        if r.state not in (*ATTENTION, ReminderState.scheduled.value):
            raise Validation(f"A {r.state} reminder cannot be dismissed")
        r.state, r.updated_at = ReminderState.dismissed.value, self.dts.now_utc()
        self.session.flush()
        self._emit(r.task_id)
        return r

    # ------------------------------------------------------------------ queries
    def active(self, upcoming_limit: int = 5) -> ReminderList:
        pending = Task.status == TaskStatus.pending.value
        attention = self.session.scalars(
            select(Reminder)
            .join(Reminder.task)
            .where(Reminder.state.in_(ATTENTION), pending)
            .order_by(Reminder.fire_at.desc())
        )
        upcoming = self.session.scalars(
            select(Reminder)
            .join(Reminder.task)
            .where(Reminder.state == ReminderState.scheduled.value, pending)
            .order_by(Reminder.fire_at.asc())
            .limit(upcoming_limit)
        )
        return ReminderList(
            attention=[reminder_out(r) for r in attention],
            upcoming=[reminder_out(r) for r in upcoming],
        )
