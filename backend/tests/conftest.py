"""Test wiring: temp data dir + DB per test, FakeClock, authenticated httpx client."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.core import config as config_mod
from app.core.clock import FakeClock
from app.database import engine as engine_mod
from tests.fakes import FakeAudio, FakeConnector

TOKEN = "test-token-1234567890"
TZ = "Asia/Karachi"  # UTC+5, no DST → deterministic boundaries
START = datetime(2026, 10, 26, 22, 30, tzinfo=ZoneInfo(TZ))  # 22:30 local = 17:30 UTC same day


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(START)


@pytest.fixture
def env(tmp_path, monkeypatch) -> Iterator[None]:
    monkeypatch.setenv("ZIKO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ZIKO_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("ZIKO_TOKEN", TOKEN)
    monkeypatch.setenv("ZIKO_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.fail.Keyring")  # force file fallback
    config_mod.reset_config()
    engine_mod.dispose_engine()
    yield
    engine_mod.dispose_engine()
    config_mod.reset_config()


@pytest.fixture
async def client(env, clock) -> AsyncIterator[httpx.AsyncClient]:
    from app.main import create_app

    app = create_app(
        clock=clock, run_scheduler=False, run_wakeword=False
    )  # tests drive scheduler.tick() directly
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ) as c:
            # set the user's timezone so date math is deterministic
            r = await c.patch("/settings", json={"tasks": {"timezone": TZ}})
            assert r.status_code == 200, r.text
            yield c


@pytest.fixture
async def anon(env, clock) -> AsyncIterator[httpx.AsyncClient]:
    from app.main import create_app

    app = create_app(
        clock=clock, run_scheduler=False, run_wakeword=False
    )  # tests drive scheduler.tick() directly
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield c


# ---------------------------------------------------------------- voice stack with fakes (no network, no mic)
@pytest.fixture
def connector() -> FakeConnector:
    return FakeConnector()


@pytest.fixture
def audio() -> FakeAudio:
    return FakeAudio()


@pytest.fixture
async def app(env, clock, connector, audio, monkeypatch):
    from app.main import create_app

    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    a = create_app(
        clock=clock,
        run_scheduler=False,
        run_wakeword=False,
        live_connector=connector,
        audio_factory=lambda: audio,
    )
    async with a.router.lifespan_context(a):
        yield a


@pytest.fixture
async def api(app) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as c:
        assert (await c.patch("/settings", json={"tasks": {"timezone": TZ}})).status_code == 200
        yield c
