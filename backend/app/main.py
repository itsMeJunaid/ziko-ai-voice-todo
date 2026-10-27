"""Ziko local backend. Binds to 127.0.0.1 only; Tauri passes ZIKO_PORT/ZIKO_TOKEN (PRD §8.5)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import health, reminders, settings, tasks, voice, ws
from app.core.clock import Clock, SystemClock
from app.core.config import get_config
from app.core.errors import install_error_handlers
from app.core.logging import setup_logging
from app.database.engine import session_scope
from app.database.migrate import upgrade_to_head
from app.services.audio_io import DeviceAudio
from app.services.gemini_live_service import GeminiLiveConnector, LiveConnector
from app.services.scheduler import HubNotifier, OsNotifier, ReminderScheduler
from app.services.settings_service import CredentialStore, SettingsService
from app.services.voice_service import VoiceService, api_key_lookup
from app.services.wakeword.detector import LiveKitDetector
from app.services.wakeword.service import WakeWordService
from app.tools.registry import ToolRegistry
from app.tools.task_tools import TOOLS

log = logging.getLogger(__name__)


def create_app(
    clock: Clock | None = None,
    *,
    run_migrations: bool = True,
    run_scheduler: bool = True,
    run_wakeword: bool = True,
    live_connector: LiveConnector | None = None,
    audio_factory=None,
) -> FastAPI:
    setup_logging()
    cfg = get_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if run_migrations:
            upgrade_to_head()
        log.info(
            "Ziko backend %s ready on %s:%s (db=%s)",
            __version__,
            cfg.host,
            cfg.port,
            cfg.database_path,
        )
        # PRD §7.1: reminders run in the backend, independent of the AI and of any window being open.
        ticker = asyncio.create_task(app.state.scheduler.run()) if run_scheduler else None
        listener = asyncio.create_task(app.state.wakeword.run()) if run_wakeword else None
        yield
        if listener:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener
        app.state.wakeword.close()
        await app.state.voice.stop()  # mic off, session closed (PRD §8.5 clean exit)
        if ticker:
            ticker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ticker
        log.info("Ziko backend shutting down")

    app = FastAPI(title="Ziko Backend", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.clock = clock or SystemClock()
    app.state.credentials = CredentialStore()
    app.state.scheduler = ReminderScheduler(app.state.clock, HubNotifier(fallback=OsNotifier()))

    def load_settings():
        with session_scope() as s:
            return SettingsService(s, app.state.clock).get()

    def device_audio():
        import asyncio

        return DeviceAudio(asyncio.get_running_loop(), load_settings().voice.mic_device)

    app.state.voice = VoiceService(
        registry=ToolRegistry(app.state.clock, TOOLS),
        connector=live_connector or GeminiLiveConnector(),
        audio_factory=audio_factory or device_audio,
        api_key=api_key_lookup(app.state.credentials),
        settings=load_settings,
    )
    app.state.wakeword = WakeWordService(
        voice=app.state.voice, settings=load_settings, detector_factory=lambda t: LiveKitDetector(threshold=t)
    )
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(health.router)
    app.include_router(tasks.router)
    app.include_router(tasks.summary_router)
    app.include_router(reminders.router)
    app.include_router(settings.router)
    app.include_router(voice.router)
    app.include_router(ws.router)
    return app


def _exit_when_parent_dies() -> None:
    """Tauri keeps our stdin pipe open; EOF means the desktop app is gone (even after a crash)."""
    import os
    import sys
    import threading

    def watch() -> None:
        try:
            while sys.stdin.read(1024):
                pass
        except Exception:
            pass
        log.warning("stdin closed (parent exited) — shutting down")
        os._exit(0)

    threading.Thread(target=watch, name="parent-watchdog", daemon=True).start()


def main() -> None:
    import uvicorn

    setup_logging()
    cfg = get_config()
    if cfg.host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("Refusing to bind to a non-loopback address (ZIKO_HOST)")
    if cfg.exit_on_stdin_eof:
        _exit_when_parent_dies()
    uvicorn.run(
        create_app(),
        host=cfg.host,
        port=cfg.port,
        log_level=cfg.log_level.lower(),
        access_log=False,
        log_config=None,  # uvicorn logs via our root handlers: file rotation + token redaction
    )


if __name__ == "__main__":
    main()
