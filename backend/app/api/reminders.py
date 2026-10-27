from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import Ctx, get_ctx
from app.schemas.reminder import ReminderList, ReminderOut, SnoozeIn
from app.services.reminder_service import reminder_out

router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.get("", response_model=ReminderList)
async def list_reminders(ctx: Ctx = Depends(get_ctx)) -> ReminderList:
    """The panel's "Upcoming reminders" card (PRD §3.2-D): fired-but-unacknowledged, then the next ones."""
    return ctx.tasks.reminders.active()


@router.post("/{reminder_id}/snooze", response_model=ReminderOut)
async def snooze_reminder(
    reminder_id: str, body: SnoozeIn | None = None, ctx: Ctx = Depends(get_ctx)
) -> ReminderOut:
    minutes = (body.minutes if body else None) or ctx.settings.tasks.snooze_minutes
    return reminder_out(ctx.tasks.reminders.snooze(reminder_id, minutes))


@router.post("/{reminder_id}/dismiss", response_model=ReminderOut)
async def dismiss_reminder(reminder_id: str, ctx: Ctx = Depends(get_ctx)) -> ReminderOut:
    return reminder_out(ctx.tasks.reminders.dismiss(reminder_id))
