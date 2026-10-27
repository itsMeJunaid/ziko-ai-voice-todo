"""Views (today / upcoming / overdue / completed) and local-day boundaries (PRD §6.1, §5.2)."""


async def _mk(client, title, due=None, **kw):
    body = {"title": title, **kw}
    if due:
        body["due_at"] = due
    r = await client.post("/tasks", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_today_window_uses_local_day_not_utc_day(client, clock):
    # Clock: 2026-10-26 22:30 local (17:30Z). A task at 23:30 local today is 18:30Z → still "today" locally,
    # but it is 2026-10-26 in UTC too; the interesting one is 00:30 local tomorrow = 19:30Z TODAY in UTC.
    late_today = await _mk(client, "late today", "2026-10-26T23:30:00")
    early_tomorrow = await _mk(client, "early tomorrow", "2026-10-27T00:30:00")  # 19:30Z on the 26th
    undated = await _mk(client, "undated")
    today = {t["title"] for t in (await client.get("/tasks", params={"view": "today"})).json()["items"]}
    upcoming = {t["title"] for t in (await client.get("/tasks", params={"view": "upcoming"})).json()["items"]}
    assert today == {"late today", "undated"}
    assert upcoming == {"early tomorrow"}
    assert late_today["due_at"].startswith("2026-10-26T18:30") and early_tomorrow["due_at"].startswith(
        "2026-10-26T19:30"
    )
    assert undated["due_at"] is None


async def test_overdue_flag_and_view(client, clock):
    t = await _mk(client, "soon", "2026-10-26T23:00:00")  # in 30 min local
    assert (await client.get(f"/tasks/{t['id']}")).json()["is_overdue"] is False
    clock.advance(hours=1)
    got = (await client.get(f"/tasks/{t['id']}")).json()
    assert got["is_overdue"] is True
    overdue = (await client.get("/tasks", params={"view": "overdue"})).json()["items"]
    assert [x["id"] for x in overdue] == [t["id"]]
    # overdue tasks stay in Today (fixed MVP default)
    assert t["id"] in {
        x["id"] for x in (await client.get("/tasks", params={"view": "today"})).json()["items"]
    }


async def test_completed_view_respects_retention(client, clock):
    t = await _mk(client, "old")
    await client.post(f"/tasks/{t['id']}/complete")
    assert (await client.get("/tasks", params={"view": "completed"})).json()["count"] == 1
    clock.advance(days=31)
    assert (await client.get("/tasks", params={"view": "completed"})).json()["count"] == 0


async def test_ordering_dated_before_undated(client):
    await _mk(client, "undated")
    await _mk(client, "later", "2026-10-26T23:50:00")
    await _mk(client, "sooner", "2026-10-26T23:10:00")
    titles = [t["title"] for t in (await client.get("/tasks", params={"view": "today"})).json()["items"]]
    assert titles == ["sooner", "later", "undated"]


async def test_search_filter(client):
    await _mk(client, "Write RAG evaluation")
    await _mk(client, "Buy milk")
    items = (await client.get("/tasks", params={"view": "all", "q": "rag"})).json()["items"]
    assert [t["title"] for t in items] == ["Write RAG evaluation"]


async def test_daily_summary_reflects_db_state(client, clock):
    await _mk(client, "overdue one", "2026-10-26T20:00:00")
    await _mk(client, "due later", "2026-10-26T23:45:00", reminder_enabled=True)
    done = await _mk(client, "done")
    await client.post(f"/tasks/{done['id']}/complete")
    s = (await client.get("/summary/today")).json()
    assert s["date"] == "2026-10-26" and s["timezone"] == "Asia/Karachi"
    assert [t["title"] for t in s["overdue"]] == ["overdue one"]
    assert [t["title"] for t in s["today"]] == ["due later"]
    assert [t["title"] for t in s["upcoming_reminders"]] == ["due later"]
    assert s["completed_today"] == 1


async def test_invalid_timezone_rejected(client):
    r = await client.patch("/settings", json={"tasks": {"timezone": "Mars/Olympus"}})
    assert r.status_code == 200  # settings accept any string…
    r = await client.get("/tasks")  # …but using it is an actionable error, not a crash (PRD §10.3)
    assert r.status_code == 422 and "timezone" in r.json()["error"]["message"].lower()
