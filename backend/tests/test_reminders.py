"""Reminder engine with an injected fake clock (PRD §7.4, §14 Reminders). Starts 22:30 Karachi (17:30Z)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update

from app.database.engine import session_scope
from app.models.reminder import Reminder
from app.services.scheduler import ReminderScheduler

REMIND_AT = "2026-10-26T23:00:00"  # local, 30 min after the fake clock's start


class FakeNotifier:
    def __init__(self, *, up: bool = True, fail: bool = False) -> None:
        self.up, self.fail, self.sent = up, fail, []

    def available(self) -> bool:
        return self.up

    def deliver(self, payload) -> None:
        if self.fail:
            raise RuntimeError("notification daemon gone")
        self.sent.append(payload["reminder"])


def states(task_id: str) -> list[str]:
    with session_scope() as s:
        rows = s.scalars(select(Reminder).where(Reminder.task_id == task_id).order_by(Reminder.created_at))
        return [r.state for r in rows]


async def make_task(client, **extra) -> dict:
    r = await client.post("/tasks", json={"title": "Call the bank", "reminder_at": REMIND_AT, **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def test_creating_a_task_with_a_reminder_schedules_it(client):
    t = await make_task(client)
    assert states(t["id"]) == ["scheduled"]
    body = (await client.get("/reminders")).json()
    assert body["attention"] == [] and [r["task_title"] for r in body["upcoming"]] == ["Call the bank"]


async def test_fires_once_at_the_scheduled_time(client, clock):
    t = await make_task(client)
    n = FakeNotifier()
    sched = ReminderScheduler(clock, n)
    assert sched.tick().delivered == []
    clock.advance(minutes=29, seconds=59)
    assert sched.tick().delivered == []
    clock.advance(seconds=1)
    assert len(sched.tick().delivered) == 1
    assert sched.tick().delivered == [] and sched.tick().delivered == []  # no duplicates
    assert len(n.sent) == 1 and n.sent[0]["task_title"] == "Call the bank" and n.sent[0]["missed"] is False
    assert states(t["id"]) == ["delivered"]
    att = (await client.get("/reminders")).json()["attention"]
    assert [r["state"] for r in att] == ["delivered"]


async def test_completing_or_archiving_cancels_and_reopening_restores(client, clock):
    n = FakeNotifier()
    sched = ReminderScheduler(clock, n)
    a = await make_task(client)
    b = await make_task(client, title="Pay rent")
    await client.post(f"/tasks/{a['id']}/complete")
    await client.post(f"/tasks/{b['id']}/archive")
    assert states(a["id"]) == ["cancelled"] and states(b["id"]) == ["cancelled"]
    await client.post(f"/tasks/{a['id']}/reopen")  # still in the future → comes back
    assert states(a["id"]) == ["cancelled", "scheduled"]
    clock.advance(minutes=30)
    sched.tick()
    assert [r["task_id"] for r in n.sent] == [a["id"]]
    # reopening after the time has passed must not resurrect it
    await client.post(f"/tasks/{b['id']}/reopen")
    assert states(b["id"]) == ["cancelled"]


async def test_completing_a_fired_task_clears_it_from_the_card(client, clock):
    t = await make_task(client)
    clock.advance(minutes=30)
    ReminderScheduler(clock, FakeNotifier()).tick()
    await client.post(f"/tasks/{t['id']}/complete")
    assert states(t["id"]) == ["dismissed"]
    assert (await client.get("/reminders")).json() == {"attention": [], "upcoming": []}


async def test_changing_the_time_reschedules_and_unrelated_edits_do_not(client, clock):
    t = await make_task(client)
    await client.patch(f"/tasks/{t['id']}", json={"title": "Call the bank (urgent)"})
    assert states(t["id"]) == ["scheduled"]
    await client.patch(f"/tasks/{t['id']}", json={"reminder_at": "2026-10-26T23:10:00"})
    assert states(t["id"]) == ["cancelled", "scheduled"]
    n = FakeNotifier()
    sched = ReminderScheduler(clock, n)
    clock.advance(minutes=30)
    assert sched.tick().delivered == []
    clock.advance(minutes=10)
    assert len(sched.tick().delivered) == 1 and n.sent[0]["task_title"] == "Call the bank (urgent)"
    await client.patch(f"/tasks/{t['id']}", json={"reminder_at": None})
    assert states(t["id"])[-1] == "dismissed"


async def test_survives_a_restart(client, clock):
    t = await make_task(client)
    ReminderScheduler(clock, FakeNotifier()).tick()  # first process: nothing due yet
    clock.advance(minutes=30)
    n = FakeNotifier()
    assert len(ReminderScheduler(clock, n).tick().delivered) == 1  # fresh scheduler, same DB
    assert states(t["id"]) == ["delivered"]


async def test_sleeping_through_a_reminder_delivers_it_once_as_missed(client, clock):
    t = await make_task(client)
    n = FakeNotifier()
    sched = ReminderScheduler(clock, n)
    sched.tick()
    clock.advance(hours=3)  # laptop asleep
    res = sched.tick()
    assert res.missed == res.delivered and len(res.delivered) == 1
    assert n.sent[0]["missed"] is True
    assert sched.tick().delivered == [] and len(n.sent) == 1
    assert states(t["id"]) == ["missed"]
    assert (await client.get("/reminders")).json()["attention"][0]["missed"] is True


async def test_without_a_channel_it_waits_then_reports_missed(client, clock):
    t = await make_task(client)
    n = FakeNotifier(up=False)
    sched = ReminderScheduler(clock, n)
    clock.advance(minutes=30)
    sched.tick()
    assert states(t["id"]) == ["scheduled"]  # not claimed: nobody could see it
    clock.advance(minutes=2)
    sched.tick()
    assert states(t["id"]) == ["missed"] and n.sent == []
    n.up = True
    assert len(sched.tick().delivered) == 1 and n.sent[0]["missed"] is True


async def test_a_crash_mid_delivery_is_never_resent(client, clock):
    t = await make_task(client)
    with session_scope() as s:  # what a crash between claim and "delivered" leaves behind
        s.execute(update(Reminder).values(state="delivering"))
    n = FakeNotifier()
    clock.advance(minutes=30)
    res = ReminderScheduler(clock, n).tick()
    assert len(res.interrupted) == 1 and n.sent == []
    assert states(t["id"]) == ["failed"]


async def test_failed_delivery_is_recorded_not_retried(client, clock):
    t = await make_task(client)
    n = FakeNotifier(fail=True)
    sched = ReminderScheduler(clock, n)
    clock.advance(minutes=30)
    assert len(sched.tick().failed) == 1
    assert sched.tick().failed == []
    with session_scope() as s:
        r = s.scalars(select(Reminder).where(Reminder.task_id == t["id"])).one()
        assert r.state == "failed" and r.attempts == 1 and "daemon" in r.last_error


async def test_two_schedulers_on_one_db_deliver_once(client, clock):
    await make_task(client)
    n = FakeNotifier()
    a, b = ReminderScheduler(clock, n), ReminderScheduler(clock, n)
    clock.advance(minutes=30)
    a.tick()
    b.tick()
    assert len(n.sent) == 1


async def test_snooze_and_dismiss(client, clock):
    t = await make_task(client)
    n = FakeNotifier()
    sched = ReminderScheduler(clock, n)
    first = (await client.get("/reminders")).json()["upcoming"][0]
    r = await client.post(f"/reminders/{first['id']}/snooze")
    assert r.status_code == 422  # nothing to snooze before it fires
    clock.advance(minutes=30)
    sched.tick()
    r = await client.post(f"/reminders/{first['id']}/snooze")  # default 10 min from settings
    assert r.status_code == 200, r.text
    again = r.json()
    assert again["state"] == "scheduled" and again["id"] != first["id"]
    assert again["fire_at"].startswith("2026-10-26T18:10:00")  # 23:10 local
    assert states(t["id"]) == ["snoozed", "scheduled"]
    clock.advance(minutes=10)
    sched.tick()
    assert len(n.sent) == 2
    r = await client.post(f"/reminders/{again['id']}/dismiss")
    assert r.status_code == 200 and r.json()["state"] == "dismissed"
    assert (await client.get("/reminders")).json() == {"attention": [], "upcoming": []}
    assert (await client.post(f"/reminders/{again['id']}/dismiss")).status_code == 422
    r = await client.post(f"/reminders/{again['id']}/snooze", json={"minutes": 5})
    assert r.status_code == 422


async def test_snooze_minutes_can_be_given(client, clock):
    await make_task(client)
    clock.advance(minutes=30)
    ReminderScheduler(clock, FakeNotifier()).tick()
    rid = (await client.get("/reminders")).json()["attention"][0]["id"]
    r = await client.post(f"/reminders/{rid}/snooze", json={"minutes": 5})
    assert r.json()["fire_at"].startswith("2026-10-26T18:05:00")
    assert (await client.post("/reminders/nope/dismiss")).status_code == 404


async def test_scheduler_runs_with_the_app(env, clock):
    """The lifespan starts the ticker (PRD §7.1: no window or AI needed)."""
    from app.main import create_app

    app = create_app(clock=clock, run_wakeword=False)
    async with app.router.lifespan_context(app):
        assert isinstance(app.state.scheduler, ReminderScheduler)
        assert app.state.scheduler.grace == timedelta(seconds=60)
