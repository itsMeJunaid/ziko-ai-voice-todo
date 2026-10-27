from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import Ctx, get_ctx
from app.schemas.common import Ok
from app.schemas.task import DailySummary, TaskCreate, TaskList, TaskOut, TaskUpdate, View

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=TaskList)
async def list_tasks(
    view: View = "today",
    q: str | None = Query(default=None, max_length=200),
    ctx: Ctx = Depends(get_ctx),
) -> TaskList:
    items = [ctx.tasks.to_out(t) for t in ctx.tasks.list(view, q)]
    return TaskList(items=items, view=view, count=len(items))


@router.post("", response_model=TaskOut, status_code=201)
async def create_task(body: TaskCreate, ctx: Ctx = Depends(get_ctx)) -> TaskOut:
    return ctx.tasks.to_out(ctx.tasks.create(body))


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: str, ctx: Ctx = Depends(get_ctx)) -> TaskOut:
    return ctx.tasks.to_out(ctx.tasks.get(task_id))


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(task_id: str, body: TaskUpdate, ctx: Ctx = Depends(get_ctx)) -> TaskOut:
    return ctx.tasks.to_out(ctx.tasks.update(task_id, body))


@router.post("/{task_id}/complete", response_model=TaskOut)
async def complete_task(task_id: str, ctx: Ctx = Depends(get_ctx)) -> TaskOut:
    return ctx.tasks.to_out(ctx.tasks.complete(task_id))


@router.post("/{task_id}/reopen", response_model=TaskOut)
async def reopen_task(task_id: str, ctx: Ctx = Depends(get_ctx)) -> TaskOut:
    return ctx.tasks.to_out(ctx.tasks.reopen(task_id))


@router.post("/{task_id}/archive", response_model=TaskOut)
async def archive_task(task_id: str, ctx: Ctx = Depends(get_ctx)) -> TaskOut:
    return ctx.tasks.to_out(ctx.tasks.archive(task_id))


@router.delete("", response_model=Ok)
async def delete_all_tasks(
    confirm: str = Query(..., description="must be 'DELETE'"), ctx: Ctx = Depends(get_ctx)
) -> Ok:
    """Hard delete of everything — Settings → 'Delete all local tasks' only (PRD §3.3)."""
    from app.core.errors import Validation

    if confirm != "DELETE":
        raise Validation("Pass confirm=DELETE to delete all tasks")
    ctx.tasks.delete_all()
    return Ok()


summary_router = APIRouter(tags=["summary"])


@summary_router.get("/summary/today", response_model=DailySummary)
async def daily_summary(ctx: Ctx = Depends(get_ctx)) -> DailySummary:
    """Data for the panel header + the `get_daily_summary` tool (PRD §6.2). Pure DB state, no LLM."""
    now = ctx.dts.now_utc()
    today = [ctx.tasks.to_out(t) for t in ctx.tasks.list("today")]
    overdue = [t for t in today if t.is_overdue]
    due_today = [t for t in today if not t.is_overdue]
    pending = ctx.tasks.list("pending")
    upcoming = sorted(
        (t for t in pending if t.reminder_at is not None and t.reminder_at >= now),
        key=lambda t: t.reminder_at,
    )[:5]
    return DailySummary(
        date=ctx.dts.local_date_iso(),
        timezone=ctx.dts.zone_name,
        now_local=ctx.dts.now_local(),
        today=due_today,
        overdue=overdue,
        upcoming_reminders=[ctx.tasks.to_out(t) for t in upcoming],
        completed_today=ctx.tasks.completed_today_count(),
    )
