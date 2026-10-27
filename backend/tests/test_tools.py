"""AI tool layer (PRD §5.4, §9.1, §11.5). Clock: Mon 2026-10-26 22:30 Asia/Karachi (UTC+5)."""

from __future__ import annotations

import pytest

from app.tools.registry import ToolRegistry
from app.tools.task_tools import TOOLS


@pytest.fixture
async def tools(client, clock) -> ToolRegistry:  # `client` sets the user's timezone
    return ToolRegistry(clock, TOOLS)


def test_declares_exactly_the_prd_tools(clock):
    names = {d["name"] for d in ToolRegistry(clock, TOOLS).declarations()}
    assert names == {
        "create_task", "list_tasks", "get_task", "update_task", "complete_task", "archive_task",
        "create_reminder", "update_reminder", "cancel_reminder", "get_daily_summary", "get_current_datetime",
    }  # fmt: skip
    for d in ToolRegistry(clock, TOOLS).declarations():
        schema = d["parameters_json_schema"]
        assert schema["type"] == "object" and "$defs" not in str(schema) and "anyOf" not in str(schema)


async def test_current_datetime_is_local(tools):
    r = tools.execute("get_current_datetime", {})
    assert r["ok"] and r["now"] == "2026-10-26T22:30+05:00" and r["weekday"] == "Monday"
    assert r["timezone"] == "Asia/Karachi" and r["tomorrow_morning_hour"] == 9


async def test_create_task_in_local_time_and_it_is_really_saved(tools, client):
    r = tools.execute(
        "create_task",
        {"title": "Finish project", "due_at": "2026-10-27T10:00", "reminder_minutes_before": 30},
    )
    assert r["ok"], r
    assert r["task"]["due"] == "Tue 2026-10-27 10:00" and r["task"]["reminder"] == "Tue 2026-10-27 09:30"
    saved = (await client.get(f"/tasks/{r['task']['id']}")).json()
    assert saved["source"] == "voice" and saved["due_at"].startswith("2026-10-27T05:00:00")
    assert (await client.get("/reminders")).json()["upcoming"][0]["task_title"] == "Finish project"


async def test_a_wrong_offset_is_re_anchored_to_local_wall_time(tools):
    r = tools.execute("create_task", {"title": "Standup", "due_at": "2026-10-27T10:00:00Z"})
    assert r["task"]["due"] == "Tue 2026-10-27 10:00" and "local time" in r["note"]
    same = tools.execute("create_task", {"title": "Lunch", "due_at": "2026-10-27T13:00:00+05:00"})
    assert same["task"]["due"] == "Tue 2026-10-27 13:00" and "note" not in same


async def test_a_day_without_a_time_means_the_end_of_that_day(tools):
    r = tools.execute("create_task", {"title": "Call about the trip", "due_at": "2026-10-30"})
    assert r["task"]["due"] == "Fri 2026-10-30 23:59"


async def test_invalid_arguments_are_rejected_without_side_effects(tools, client):
    assert tools.execute("create_task", {"title": ""})["error"]["code"] == "invalid_arguments"
    assert tools.execute("create_task", {"title": "x", "priority": "urgent"})["error"]["code"] == (
        "invalid_arguments"
    )
    assert tools.execute("create_task", {"title": "x", "due_at": "next friday"})["error"]["code"] == (
        "validation_error"
    )
    r = tools.execute("create_task", {"title": "x", "reminder_minutes_before": 10})
    assert r["error"]["message"].startswith("A reminder relative")
    assert tools.execute("drop_table", {"sql": "DROP TABLE tasks"})["error"]["code"] == "unknown_tool"
    assert (await client.get("/tasks?view=pending")).json()["count"] == 0


async def test_ambiguous_title_returns_candidates_to_ask_about(tools):
    tools.execute("create_task", {"title": "Call mom"})
    tools.execute("create_task", {"title": "Call mom about the trip"})
    r = tools.execute("complete_task", {"task": "call"})
    assert r["ok"] is False and r["error"]["code"] == "ambiguous"
    assert {c["title"] for c in r["error"]["candidates"]} == {"Call mom", "Call mom about the trip"}
    exact = tools.execute("complete_task", {"task": "call mom"})  # exact title wins
    assert exact["ok"] and exact["task"]["title"] == "Call mom" and exact["task"]["status"] == "completed"
    assert tools.execute("get_task", {"task": "dentist"})["error"]["code"] == "not_found"


async def test_update_list_and_get(tools):
    t = tools.execute("create_task", {"title": "Report", "due_at": "2026-10-28T09:00"})["task"]
    r = tools.execute("update_task", {"task": t["id"], "due_at": "2026-10-31T16:00", "priority": "high"})
    assert r["task"]["due"] == "Sat 2026-10-31 16:00" and r["task"]["priority"] == "high"
    assert (
        tools.execute("update_task", {"task": "report"})["error"]["message"] == "Nothing to change was given"
    )
    assert [x["title"] for x in tools.execute("list_tasks", {"view": "upcoming"})["tasks"]] == ["Report"]
    assert tools.execute("list_tasks", {})["count"] == 0  # nothing due today
    cleared = tools.execute("update_task", {"task": "report", "clear_due": True})
    assert cleared["task"]["due"] is None
    assert tools.execute("get_task", {"task": "Report"})["task"]["description"] is None


async def test_archive_needs_explicit_confirmation(tools, client):
    t = tools.execute("create_task", {"title": "Old meeting"})["task"]
    first = tools.execute("archive_task", {"task": "old meeting"})
    assert first["ok"] is False and first["needs_confirmation"] is True
    assert (await client.get(f"/tasks/{t['id']}")).json()["status"] == "pending"
    done = tools.execute("archive_task", {"task": "old meeting", "confirmed": True})
    assert done["ok"] and done["task"]["status"] == "archived"


async def test_reminder_tools(tools, client):
    tools.execute("create_task", {"title": "Dentist", "due_at": "2026-10-27T15:00"})
    r = tools.execute("create_reminder", {"task": "dentist", "minutes_before_due": 60})
    assert r["task"]["reminder"] == "Tue 2026-10-27 14:00"
    r = tools.execute("update_reminder", {"task": "dentist", "at": "2026-10-27T14:30"})
    assert r["task"]["reminder"] == "Tue 2026-10-27 14:30"
    both = tools.execute(
        "update_reminder", {"task": "dentist", "at": "2026-10-27T14:00", "minutes_before_due": 5}
    )
    assert both["error"]["code"] == "validation_error"
    late = tools.execute("create_reminder", {"task": "dentist", "minutes_before_due": 99999})
    assert late["error"]["code"] == "invalid_arguments"
    past = tools.execute("update_reminder", {"task": "dentist", "at": "2026-10-20T09:00"})
    assert past["ok"] is False and "past" in past["error"]["message"]
    assert tools.execute("cancel_reminder", {"task": "dentist"})["task"]["reminder"] is None
    assert tools.execute("cancel_reminder", {"task": "dentist"})["error"]["code"] == "not_found"
    assert (await client.get("/reminders")).json()["upcoming"] == []


async def test_daily_summary_reflects_the_database(tools, clock):
    tools.execute("create_task", {"title": "Overdue thing", "due_at": "2026-10-26T23:00"})
    tools.execute("create_task", {"title": "Late call", "due_at": "2026-10-26T23:50", "priority": "high"})
    tools.execute("create_task", {"title": "Undated"})
    tools.execute(
        "create_task", {"title": "Tomorrow", "due_at": "2026-10-27T09:00", "reminder_at": "2026-10-27T08:45"}
    )
    tools.execute("complete_task", {"task": "undated"})
    clock.advance(minutes=40)  # 23:10 → "Overdue thing" is now overdue
    s = tools.execute("get_daily_summary", {})
    assert [b["title"] for b in s["overdue"]] == ["Overdue thing"]
    assert [b["title"] for b in s["due_today"]] == ["Late call"]
    assert s["upcoming_reminders"] == [{"task": "Tomorrow", "at": "Tue 2026-10-27 08:45"}]
    assert s["completed_today"] == 1
