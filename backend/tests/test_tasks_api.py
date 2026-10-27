"""Task CRUD + status transitions + validation (PRD §5.1, §14 Tasks)."""


async def test_create_defaults_and_persist(client):
    r = await client.post("/tasks", json={"title": "  Finish AI project  "})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["title"] == "Finish AI project"
    assert t["status"] == "pending" and t["priority"] == "medium" and t["source"] == "ui"
    assert t["timezone"] == "Asia/Karachi" and t["due_at"] is None and t["is_overdue"] is False
    r2 = await client.get(f"/tasks/{t['id']}")
    assert r2.status_code == 200 and r2.json()["id"] == t["id"]


async def test_validation_rejects_bad_title_and_priority(client):
    assert (await client.post("/tasks", json={"title": "   "})).status_code == 422
    assert (await client.post("/tasks", json={"title": "x" * 201})).status_code == 422
    r = await client.post("/tasks", json={"title": "ok", "priority": "urgent"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


async def test_naive_due_is_interpreted_in_user_timezone(client):
    # 10:00 local Karachi (UTC+5) → 05:00Z
    r = await client.post("/tasks", json={"title": "Meeting", "due_at": "2026-10-27T10:00:00"})
    assert r.status_code == 201
    assert r.json()["due_at"].startswith("2026-10-27T05:00:00")


async def test_reminder_derived_from_default_offset(client):
    r = await client.post(
        "/tasks",
        json={"title": "Present", "due_at": "2026-10-27T10:00:00", "reminder_enabled": True},
    )
    assert r.status_code == 201
    assert r.json()["reminder_at"].startswith("2026-10-27T04:45:00")  # 15 min before, in UTC


async def test_reminder_after_due_or_in_past_rejected(client):
    r = await client.post(
        "/tasks",
        json={"title": "A", "due_at": "2026-10-27T10:00:00", "reminder_at": "2026-10-27T11:00:00"},
    )
    assert r.status_code == 422 and "after" in r.json()["error"]["message"]
    r = await client.post("/tasks", json={"title": "B", "reminder_at": "2026-10-20T10:00:00"})
    assert r.status_code == 422 and "past" in r.json()["error"]["message"]


async def test_update_only_requested_fields(client):
    t = (
        await client.post(
            "/tasks", json={"title": "Draft", "description": "v1", "due_at": "2026-10-28T09:00:00"}
        )
    ).json()
    r = await client.patch(f"/tasks/{t['id']}", json={"priority": "high"})
    u = r.json()
    assert r.status_code == 200 and u["priority"] == "high"
    assert u["description"] == "v1" and u["due_at"] == t["due_at"] and u["title"] == "Draft"
    assert u["updated_at"] >= t["updated_at"]


async def test_clearing_due_clears_deadline_relative_reminder(client):
    t = (
        await client.post(
            "/tasks", json={"title": "R", "due_at": "2026-10-28T09:00:00", "reminder_enabled": True}
        )
    ).json()
    assert t["reminder_at"]
    u = (await client.patch(f"/tasks/{t['id']}", json={"due_at": None})).json()
    assert u["due_at"] is None and u["reminder_at"] is None


async def test_complete_reopen_archive_transitions(client):
    t = (await client.post("/tasks", json={"title": "T"})).json()
    c = (await client.post(f"/tasks/{t['id']}/complete")).json()
    assert c["status"] == "completed" and c["completed_at"]
    # idempotent
    assert (await client.post(f"/tasks/{t['id']}/complete")).json()["completed_at"] == c["completed_at"]
    p = (await client.post(f"/tasks/{t['id']}/reopen")).json()
    assert p["status"] == "pending" and p["completed_at"] is None
    a = (await client.post(f"/tasks/{t['id']}/archive")).json()
    assert a["status"] == "archived" and a["archived_at"]
    # archived tasks are not editable, but recoverable
    assert (await client.patch(f"/tasks/{t['id']}", json={"title": "X"})).status_code == 422
    assert (await client.post(f"/tasks/{t['id']}/reopen")).json()["status"] == "pending"


async def test_status_via_patch(client):
    t = (await client.post("/tasks", json={"title": "T"})).json()
    assert (await client.patch(f"/tasks/{t['id']}", json={"status": "completed"})).json()[
        "status"
    ] == "completed"
    assert (await client.patch(f"/tasks/{t['id']}", json={"status": "pending"})).json()[
        "completed_at"
    ] is None


async def test_not_found_envelope(client):
    r = await client.get("/tasks/does-not-exist")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


async def test_delete_all_requires_confirmation(client):
    await client.post("/tasks", json={"title": "T"})
    assert (await client.delete("/tasks")).status_code == 422
    assert (await client.delete("/tasks", params={"confirm": "nope"})).status_code == 422
    assert (await client.delete("/tasks", params={"confirm": "DELETE"})).status_code == 200
    assert (await client.get("/tasks", params={"view": "all"})).json()["count"] == 0
