"""Desktop integration: CORS for the Tauri webview origin; parent-death watchdog."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.parametrize("origin", ["http://tauri.localhost", "tauri://localhost", "http://localhost:1420"])
async def test_preflight_allowed_for_tauri_origins(anon, origin):
    r = await anon.options(
        "/tasks",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == origin


async def test_preflight_refused_for_other_origins(anon):
    r = await anon.options(
        "/tasks", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}
    )
    assert "access-control-allow-origin" not in r.headers


def test_backend_exits_when_stdin_closes(tmp_path):
    env = {
        **os.environ,
        "ZIKO_DATA_DIR": str(tmp_path),
        "ZIKO_PORT": "0",
        "ZIKO_TOKEN": "t" * 24,
        "ZIKO_EXIT_ON_STDIN_EOF": "1",
        "ZIKO_LOG_LEVEL": "WARNING",
        "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.main"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(2.5)
        assert proc.poll() is None, "backend died before stdin closed"
        proc.stdin.close()  # simulate the desktop app disappearing
        proc.wait(timeout=10)
        assert proc.returncode == 0
    finally:
        if proc.poll() is None:
            proc.kill()
