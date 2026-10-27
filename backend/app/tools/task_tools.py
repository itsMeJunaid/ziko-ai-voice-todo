"""The 11 PRD §5.4 tools. Times cross this boundary as the user's local wall time ("2026-10-27T10:00"),
because that is what people say; the services store UTC."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.api.deps import Ctx
from app.core.errors import NotFound, Validation
from app.models.task import Task, TaskStatus
from app.schemas.task import TaskCreate, TaskUpdate
from app.tools.registry import Tool, error

LOCAL_TIME = (
    "Local wall time 'YYYY-MM-DDTHH:MM' in the user's timezone (from get_current_datetime); "
    "just 'YYYY-MM-DD' when the user gave a day but no time (means end of that day)"
)
TASK_REF = "The task's id from an earlier result, or words from its title"


# ---------------------------------------------------------------------- helpers
def local_str(ctx: Ctx, dt: datetime | None) -> str | None:
    return None if dt is None else ctx.dts.to_local(dt).strftime("%a %Y-%m-%d %H:%M")


def brief(ctx: Ctx, t: Task) -> dict[str, Any]:
    out = ctx.tasks.to_out(t)
    return {
        "id": t.id,
        "title": t.title,
        "status": t.status,
        "priority": t.priority,
        "due": local_str(ctx, t.due_at),
        "reminder": local_str(ctx, t.reminder_at),
        "overdue": out.is_overdue,
    }


def parse_when(ctx: Ctx, value: str) -> tuple[datetime, str | None]:
    """Local wall time → aware UTC. An explicit offset that is not the user's is treated as a mistake (the
    model sometimes sends UTC for "10 AM") and the wall time is re-anchored to the user's zone."""
    value = value.strip()
    if len(value) == 10:  # a day without a time: by the end of that day, not midnight at its start
        value += "T23:59"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Validation(f"Could not read the time {value!r}. Use {LOCAL_TIME}.") from None
    note = None
    if dt.tzinfo is not None:
        wall = dt.replace(tzinfo=None)
        if dt.utcoffset() != wall.replace(tzinfo=ctx.dts.zone).utcoffset():
            dt, note = wall, f"Interpreted {wall:%H:%M} as local time in {ctx.dts.zone_name}."
    return ctx.dts.to_utc(dt), note  # type: ignore[return-value]


def resolve(ctx: Ctx, ref: str) -> Task:
    """An id wins; otherwise a title search that must match exactly one task (raises Ambiguous with
    candidates, so the model asks which one — PRD §5.1)."""
    t = ctx.session.get(Task, ref.strip())
    return t if t is not None else ctx.tasks.resolve_one(ref)


def ok(**data: Any) -> dict[str, Any]:
    return {"ok": True, **{k: v for k, v in data.items() if v is not None}}


# ---------------------------------------------------------------------- argument models
class NoArgs(BaseModel):
    pass


class CreateTaskArgs(BaseModel):
    title: str = Field(min_length=1, max_length=200, description="Short task title in the user's words")
    due_at: str | None = Field(default=None, description=f"Deadline. {LOCAL_TIME}")
    priority: Literal["low", "medium", "high"] | None = None
    description: str | None = Field(default=None, max_length=4000)
    reminder_minutes_before: int | None = Field(
        default=None, ge=0, le=10080, description="Remind this many minutes before the deadline"
    )
    reminder_at: str | None = Field(default=None, description=f"Exact reminder time. {LOCAL_TIME}")


class ListTasksArgs(BaseModel):
    view: Literal["today", "upcoming", "overdue", "pending", "completed"] = Field(
        default="today", description="today = due today or undated, plus overdue"
    )
    query: str | None = Field(default=None, max_length=200, description="Only titles containing this")


class TaskRefArgs(BaseModel):
    task: str = Field(min_length=1, max_length=200, description=TASK_REF)


class UpdateTaskArgs(TaskRefArgs):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    due_at: str | None = Field(default=None, description=f"New deadline. {LOCAL_TIME}")
    clear_due: bool = Field(default=False, description="Remove the deadline")
    priority: Literal["low", "medium", "high"] | None = None
    description: str | None = Field(default=None, max_length=4000)


class ArchiveTaskArgs(TaskRefArgs):
    confirmed: bool = Field(
        default=False, description="true only after the user explicitly confirmed removing this task"
    )


class ReminderArgs(TaskRefArgs):
    at: str | None = Field(default=None, description=f"Exact reminder time. {LOCAL_TIME}")
    minutes_before_due: int | None = Field(
        default=None, ge=0, le=10080, description="Or: this many minutes before the task's deadline"
    )


# ---------------------------------------------------------------------- handlers
def get_current_datetime(ctx: Ctx, _: NoArgs) -> dict[str, Any]:
    now = ctx.dts.now_local()
    s = ctx.settings.tasks
    return ok(
        now=now.isoformat(timespec="minutes"),
        weekday=now.strftime("%A"),
        timezone=ctx.dts.zone_name,
        tomorrow_morning_hour=s.default_morning_hour,
        tonight_hour=s.default_evening_hour,
    )


def create_task(ctx: Ctx, a: CreateTaskArgs) -> dict[str, Any]:
    due, note = parse_when(ctx, a.due_at) if a.due_at else (None, None)
    reminder = None
    if a.reminder_at:
        reminder, n2 = parse_when(ctx, a.reminder_at)
        note = note or n2
    elif a.reminder_minutes_before is not None:
        if due is None:
            return error("validation_error", "A reminder relative to the deadline needs a deadline")
        reminder = due - timedelta(minutes=a.reminder_minutes_before)
    t = ctx.tasks.create(
        TaskCreate(
            title=a.title,
            description=a.description,
            priority=a.priority,
            due_at=due,
            reminder_at=reminder,
            source="voice",
        )
    )
    return ok(task=brief(ctx, t), note=note)


def list_tasks(ctx: Ctx, a: ListTasksArgs) -> dict[str, Any]:
    rows = ctx.tasks.list(a.view, a.query, limit=25)
    return ok(view=a.view, count=len(rows), tasks=[brief(ctx, t) for t in rows])


def get_task(ctx: Ctx, a: TaskRefArgs) -> dict[str, Any]:
    t = resolve(ctx, a.task)
    return ok(task=brief(ctx, t) | {"description": t.description})


def update_task(ctx: Ctx, a: UpdateTaskArgs) -> dict[str, Any]:
    t = resolve(ctx, a.task)
    fields: dict[str, Any] = {}
    note = None
    if a.title is not None:
        fields["title"] = a.title
    if a.priority is not None:
        fields["priority"] = a.priority
    if a.description is not None:
        fields["description"] = a.description
    if a.clear_due:
        fields["due_at"] = None
    elif a.due_at:
        fields["due_at"], note = parse_when(ctx, a.due_at)
    if not fields:
        return error("validation_error", "Nothing to change was given")
    t = ctx.tasks.update(t.id, TaskUpdate(**fields))
    return ok(task=brief(ctx, t), note=note)


def complete_task(ctx: Ctx, a: TaskRefArgs) -> dict[str, Any]:
    t = ctx.tasks.complete(resolve(ctx, a.task).id)
    return ok(task=brief(ctx, t), reminders="any future reminder for this task was cancelled")


def archive_task(ctx: Ctx, a: ArchiveTaskArgs) -> dict[str, Any]:
    t = resolve(ctx, a.task)
    if not a.confirmed:  # PRD §11.5: confirm destructive operations
        return {
            "ok": False,
            "needs_confirmation": True,
            "task": brief(ctx, t),
            "message": "Ask the user to confirm removing this task, then call again with confirmed=true.",
        }
    t = ctx.tasks.archive(t.id)
    return ok(task=brief(ctx, t), recoverable="It can be restored from the Archived tab")


def _reminder_time(ctx: Ctx, t: Task, a: ReminderArgs) -> tuple[datetime, str | None]:
    if (a.at is None) == (a.minutes_before_due is None):
        raise Validation("Give exactly one of 'at' or 'minutes_before_due'")
    if a.at is not None:
        return parse_when(ctx, a.at)
    if t.due_at is None:
        raise Validation("This task has no deadline; give an exact reminder time instead")
    return t.due_at - timedelta(minutes=a.minutes_before_due or 0), None


def set_reminder(ctx: Ctx, a: ReminderArgs) -> dict[str, Any]:
    t = resolve(ctx, a.task)
    if t.status != TaskStatus.pending:
        raise Validation("Reminders can only be set on pending tasks")
    at, note = _reminder_time(ctx, t, a)
    t = ctx.tasks.update(t.id, TaskUpdate(reminder_at=at))
    return ok(task=brief(ctx, t), note=note)


def cancel_reminder(ctx: Ctx, a: TaskRefArgs) -> dict[str, Any]:
    t = resolve(ctx, a.task)
    if t.reminder_at is None:
        raise NotFound(f"'{t.title}' has no reminder")
    t = ctx.tasks.update(t.id, TaskUpdate(reminder_at=None))
    return ok(task=brief(ctx, t))


def get_daily_summary(ctx: Ctx, _: NoArgs) -> dict[str, Any]:
    """PRD §6.2: built from the database only; the model just phrases it."""
    rank = {"high": 0, "medium": 1, "low": 2}
    today = [brief(ctx, t) for t in ctx.tasks.list("today")]
    today.sort(key=lambda b: (b["due"] is None, b["due"] or "", rank[b["priority"]]))
    reminders = ctx.tasks.reminders.active(upcoming_limit=5)
    return ok(
        now=ctx.dts.now_local().strftime("%A %Y-%m-%d %H:%M"),
        overdue=[b for b in today if b["overdue"]],
        due_today=[b for b in today if not b["overdue"]],
        upcoming_reminders=[
            {"task": r.task_title, "at": local_str(ctx, r.fire_at)} for r in reminders.upcoming
        ],
        completed_today=ctx.tasks.completed_today_count(),
    )


TOOLS = [
    Tool(
        "get_current_datetime",
        "The user's current local date, time and timezone. Call before resolving "
        "any relative date like 'tomorrow' or 'in two hours'.",
        NoArgs,
        get_current_datetime,
    ),
    Tool(
        "create_task",
        "Create a to-do task. Confirm the interpreted date and time in your reply.",
        CreateTaskArgs,
        create_task,
    ),
    Tool("list_tasks", "List the user's tasks.", ListTasksArgs, list_tasks),
    Tool("get_task", "Look up one task.", TaskRefArgs, get_task),
    Tool(
        "update_task",
        "Change a task's title, deadline, priority or description.",
        UpdateTaskArgs,
        update_task,
    ),
    Tool("complete_task", "Mark a task as done.", TaskRefArgs, complete_task),
    Tool(
        "archive_task",
        "Remove (archive) a task. Recoverable. First call without confirmed, ask the user, "
        "then call again with confirmed=true.",
        ArchiveTaskArgs,
        archive_task,
    ),
    Tool("create_reminder", "Add a reminder to a task.", ReminderArgs, set_reminder),
    Tool("update_reminder", "Move a task's reminder.", ReminderArgs, set_reminder),
    Tool("cancel_reminder", "Remove a task's reminder.", TaskRefArgs, cancel_reminder),
    Tool(
        "get_daily_summary",
        "Today's plan from the database: overdue, due today, upcoming reminders, completed count.",
        NoArgs,
        get_daily_summary,
    ),
]
