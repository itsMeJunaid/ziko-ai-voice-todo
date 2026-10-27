"""Phase 6 security pass (PRD §11) and the settings-screen endpoints."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from app.services.gemini_live_service import LiveError
from app.ws.events import hub

KEY = "AIzaSyTESTKEY_must_never_leak_0123456789"


async def test_key_test_endpoint(api, connector, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    r = (await api.post("/voice/test", json={})).json()
    assert r == {"ok": False, "code": "no_api_key", "message": r["message"]}
    r = (await api.post("/voice/test", json={"api_key": KEY})).json()
    assert r == {"ok": True, "model": "fake-live"} and connector.calls[-1]["api_key"] == KEY
    assert connector.sessions[-1].closed  # a test never leaves a session open
    connector.failures = [LiveError("invalid_key", "Gemini rejected the API key. Check it in Settings.")]
    r = (await api.post("/voice/test", json={"api_key": KEY})).json()
    assert r["ok"] is False and r["code"] == "invalid_key" and KEY not in str(r)
    assert (await api.post("/voice/test", json={"api_key": "short"})).status_code == 422


async def test_the_key_never_appears_in_responses_or_logs(api, tmp_path):
    assert (await api.put("/settings/api-key", json={"api_key": KEY})).status_code == 200
    bodies = []
    for path in [
        "/settings",
        "/settings/api-key",
        "/voice",
        "/voice/wake",
        "/health",
        "/reminders",
        "/tasks",
    ]:
        r = await api.get(path)
        assert r.status_code == 200, path
        bodies.append(r.text)
    bodies.append((await api.post("/voice/test", json={})).text)
    assert not any(KEY in b for b in bodies)
    logs = "".join(p.read_text(errors="ignore") for p in Path(os.environ["ZIKO_DATA_DIR"]).rglob("*.log*"))
    assert KEY not in logs
    stored = (await api.get("/settings/api-key")).json()
    assert stored["has_api_key"] is True


async def test_websocket_needs_the_token(app):
    from starlette.testclient import TestClient

    with TestClient(app) as c:
        try:
            with c.websocket_connect("/ws/events?token=wrong") as ws:
                ws.receive_json()
            raise AssertionError("connected without a valid token")
        except Exception as e:
            assert "4401" in str(e) or "disconnect" in type(e).__name__.lower()


def test_backend_refuses_non_loopback(monkeypatch):
    from app import main
    from app.core import config

    monkeypatch.setenv("ZIKO_HOST", "0.0.0.0")
    config.reset_config()
    try:
        main.main()
        raise AssertionError("started on a public interface")
    except SystemExit as e:
        assert "non-loopback" in str(e)
    finally:
        config.reset_config()


async def test_settings_changes_are_broadcast(api):
    q: asyncio.Queue = asyncio.Queue()
    hub._clients[q] = q
    try:
        await api.patch("/settings", json={"appearance": {"dot_opacity": 0.7}})
        await api.post("/settings/reset")
        types = [q.get_nowait()["type"] for _ in range(q.qsize())]
        assert types.count("settings.changed") == 2
    finally:
        hub._clients.pop(q, None)


async def test_settings_screen_lists(api):
    d = (await api.get("/voice/devices")).json()
    assert set(d) == {"devices", "default", "error"} and isinstance(d["devices"], list)
    assert "Puck" in (await api.get("/voice/voices")).json()["voices"]
