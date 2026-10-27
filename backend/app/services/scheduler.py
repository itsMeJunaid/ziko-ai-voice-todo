"""DB-polled reminder scheduler (PLAN §1.5, PRD §7.4). Persisted, idempotent and restart-safe by construction:

- Every tick atomically claims due rows (`scheduled → delivering`, one UPDATE … RETURNING), delivers them and
  marks them `delivered`, or `failed` with the error. A row is claimed by exactly one tick, so it fires once.
- A row more than `grace` late was not missed by a slow tick: the app was off or the computer slept. It
  becomes `missed` and is delivered once with a "missed" label. This one rule covers startup, restart and
  resume from sleep; no separate gap detection is needed.
- A row left in `delivering` by a crash may or may not have reached the user. It becomes `failed` instead of
  being sent again: no duplicate notification in recovery (PRD §14).
- With no delivery channel (no UI connected, no OS notifier) nothing is claimed; rows wait, then go `missed`.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.core.clock import Clock
from app.database.engine import session_scope
from app.models.reminder import Reminder, ReminderState
from app.models.task import Task, TaskStatus
from app.services.reminder_service import reminder_out
from app.ws.events import hub

log = logging.getLogger(__name__)


class Notifier(Protocol):
    def available(self) -> bool: ...

    def deliver(self, payload: dict[str, Any]) -> None:
        """Show the reminder. Raise on failure."""


class OsNotifier:
    """Fallback when no Ziko window is listening: a native notification straight from the backend."""

    def __init__(self) -> None:
        self._notify_send = shutil.which("notify-send") if sys.platform.startswith("linux") else None

    def available(self) -> bool:
        return sys.platform == "win32" or self._notify_send is not None

    def deliver(self, payload: dict[str, Any]) -> None:
        title, body = notification_text(payload)
        if sys.platform == "win32":
            from winotify import Notification  # optional dependency group "windows"

            Notification(app_id="Ziko", title=title, msg=body).show()
        elif self._notify_send:
            subprocess.run([self._notify_send, "--app-name=Ziko", title, body], check=True, timeout=5)
        else:
            raise RuntimeError("no OS notifier on this platform")


class HubNotifier:
    """Primary channel: `reminder.due` over the WebSocket; the dot window raises the desktop notification."""

    def __init__(self, fallback: Notifier | None = None) -> None:
        self.fallback = fallback

    def available(self) -> bool:
        return hub.client_count > 0 or (self.fallback is not None and self.fallback.available())

    def deliver(self, payload: dict[str, Any]) -> None:
        if hub.client_count > 0:
            hub.publish("reminder.due", payload)
        elif self.fallback is not None:
            self.fallback.deliver(payload)
        else:
            raise RuntimeError("no delivery channel")


def notification_text(payload: dict[str, Any]) -> tuple[str, str]:
    r = payload["reminder"]
    title = r["task_title"]
    return (f"Missed reminder: {title}" if r["missed"] else title), "Ziko reminder"


@dataclass
class TickResult:
    delivered: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    interrupted: list[str] = field(default_factory=list)


class ReminderScheduler:
    def __init__(
        self,
        clock: Clock,
        notifier: Notifier,
        *,
        tick_s: float = 1.0,
        grace: timedelta = timedelta(seconds=60),
    ) -> None:
        self.clock = clock
        self.notifier = notifier
        self.tick_s = tick_s
        self.grace = grace
        self._started = False

    def tick(self) -> TickResult:
        result = TickResult()
        now = self.clock.now_utc()
        with session_scope() as s:
            open_task = select(Task.id).where(Task.status == TaskStatus.pending.value)
            if not self._started:
                self._started = True
                result.interrupted = list(
                    s.scalars(
                        update(Reminder)
                        .where(Reminder.state == ReminderState.delivering.value)
                        .values(
                            state=ReminderState.failed.value,
                            last_error="interrupted during delivery",
                            updated_at=now,
                        )
                        .returning(Reminder.id)
                    )
                )
            # Stale rows of tasks that are no longer pending never fire (belt and braces: the task service
            # already cancels them on complete/archive).
            s.execute(
                update(Reminder)
                .where(Reminder.state == ReminderState.scheduled.value, Reminder.task_id.not_in(open_task))
                .values(state=ReminderState.cancelled.value, updated_at=now)
            )
            too_late = now - self.grace
            result.missed = list(
                s.scalars(
                    update(Reminder)
                    .where(Reminder.state == ReminderState.scheduled.value, Reminder.fire_at < too_late)
                    .values(state=ReminderState.missed.value, updated_at=now)
                    .returning(Reminder.id)
                )
            )
            if not self.notifier.available():
                return result
            claimed = list(
                s.scalars(
                    update(Reminder)
                    .where(Reminder.state == ReminderState.scheduled.value, Reminder.fire_at <= now)
                    .values(
                        state=ReminderState.delivering.value, attempts=Reminder.attempts + 1, updated_at=now
                    )
                    .returning(Reminder.id)
                )
            )
            # Missed rows are delivered once too (delivered_at marks it), with the "missed" label.
            late = list(
                s.scalars(
                    select(Reminder.id).where(
                        Reminder.state == ReminderState.missed.value, Reminder.delivered_at.is_(None)
                    )
                )
            )
            s.commit()  # the claim is durable before anything reaches the user

            rows = s.scalars(
                select(Reminder).where(Reminder.id.in_(claimed + late)).options(selectinload(Reminder.task))
            ).all()
            for r in sorted(rows, key=lambda r: r.fire_at):
                try:
                    self.notifier.deliver({"reminder": reminder_out(r).model_dump(mode="json")})
                except Exception as e:  # one bad delivery must not stop the others
                    log.warning("reminder %s delivery failed: %s", r.id, e)
                    r.state = ReminderState.failed.value  # missed ones too: never retried every tick
                    r.last_error, r.updated_at = str(e)[:500], now
                    result.failed.append(r.id)
                    continue
                if r.state == ReminderState.delivering:
                    r.state = ReminderState.delivered.value
                r.delivered_at, r.updated_at = now, now
                result.delivered.append(r.id)
        if result.delivered or result.failed or result.missed:
            hub.publish("reminder.changed", {})
        return result

    async def run(self) -> None:
        log.info("reminder scheduler started (tick %.1fs, grace %ss)", self.tick_s, self.grace.seconds)
        while True:
            try:
                self.tick()  # on the loop thread: hub queues are not thread-safe; SQLite ticks take ms
            except Exception:
                log.exception("reminder tick failed")  # keep ticking; the DB is the source of truth
            await asyncio.sleep(self.tick_s)
