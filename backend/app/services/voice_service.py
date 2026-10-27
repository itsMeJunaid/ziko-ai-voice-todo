"""Voice interaction state machine (PRD §4.3): Idle → Listening → Processing → Speaking → Listening/Idle, plus
Interrupted, Error and Muted. Publishes `voice.state` and `voice.transcript` so the UI always shows the truth.

- The Gemini session opens on demand (mic button, wake word, double-click, or a typed message) and closes
  after `interaction_timeout_s` of silence: no idle connection, no idle cloud audio (PRD §4.4, §11.2).
- Tool calls run through the ToolRegistry; the model only hears results after they are committed.
- Half-duplex with barge-in: while Ziko speaks, mic frames are dropped unless they are loud enough to be the
  user talking over it, so the speaker output is not taken for a new command (PRD §4.4 Barge-In).
- Every failure lands in the Error state with an explanation; tasks are never touched by voice failures.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import logging
import os
import time
from collections.abc import Callable
from typing import Any

from app.core.errors import Conflict
from app.schemas.settings import AppSettings
from app.services.audio_io import AudioError, AudioIO, rms
from app.services.gemini_live_service import (
    AudioOut,
    Interrupted,
    LiveConnector,
    LiveSession,
    ToolCalls,
    Transcript,
    TurnComplete,
    classify,
)
from app.tools.registry import ToolRegistry
from app.ws.events import hub

log = logging.getLogger(__name__)

PERSONA = """You are Ziko, {name}'s cheerful desktop buddy who looks after their to-do list. You're warm,
upbeat and a little playful — like a friendly assistant who's happy to help — and you speak in short,
natural sentences.
- Call the user "{name}" now and then (a greeting, a confirmation), not in every sentence.
- Small talk is welcome: if {name} says how their day is going, react kindly in a sentence, then help.
- If {name} asks for a joke, tell one short, clean, light joke (tech, office or everyday life) and laugh at it
  yourself — a real, happy laugh. Don't repeat a joke you already told in this conversation. Never joke
  about a mistake or about something {name} is worried about.
- Celebrate finished tasks briefly ("Nice one!"), and be encouraging, never pushy, about overdue ones.

Rules (these always win over personality):
- You can only act through the provided tools. Never claim you created, changed, completed or removed anything
  unless the tool result says "ok": true. If a tool returns an error, say what went wrong in plain words.
- Before interpreting any relative date or time ("tomorrow", "tonight", "next Friday", "in two hours"), call
  get_current_datetime. Send times as local wall time YYYY-MM-DDTHH:MM, without a timezone offset.
- If the user names a day but no time, send only the date (YYYY-MM-DD) and say "by end of day"; don't invent
  a time.
- "Tomorrow morning" means the tomorrow_morning_hour, "tonight" the tonight_hour from get_current_datetime.
- If a time is vague ("later", "next weekend", "soon") and a deadline matters, ask for the exact time.
- When you create a task, repeat the interpreted day and time.
- If a tool says several tasks match, list them briefly and ask which one. Never guess.
- To remove a task, call archive_task without confirmed, ask the user, then call it with confirmed=true.
- For "what's on today" or "what should I do next", use get_daily_summary and answer from it only.
- Never read out ids. Keep answers under three sentences unless the user asks for detail."""

# Sent as a hidden turn after "Hey Ziko" (never shown as something the user said).
GREETING_CUE = (
    '(The user just woke you by saying "Hey Ziko". Call get_daily_summary first. Then greet them by '
    "name in one or two short, warm sentences: say hi, ask how it's going, and give today at a glance: "
    "how many tasks are left, anything overdue, and the next deadline if there is one. If the day is "
    "empty, say so cheerfully. Then stop and wait for their request.)"
)


def system_prompt(name: str) -> str:
    return PERSONA.format(name=name.strip() or "Boss")


SYSTEM_PROMPT = system_prompt("Boss")  # default, for tests and docs

ERROR_TEXT = {
    "no_api_key": "Add your Gemini API key in Settings to use voice. Manual mode still works.",
    "muted": "The microphone is muted.",
}


class VoiceState(enum.StrEnum):
    idle = "idle"
    listening = "listening"
    processing = "processing"
    speaking = "speaking"
    interrupted = "interrupted"
    error = "error"
    muted = "muted"


class VoiceService:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        connector: LiveConnector,
        audio_factory: Callable[[], AudioIO],
        api_key: Callable[[], str | None],
        settings: Callable[[], AppSettings],
        barge_in_rms: float = 2500.0,
        speech_rms: float = 900.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.registry = registry
        self.connector = connector
        self.audio_factory = audio_factory
        self.api_key = api_key
        self.load_settings = settings
        self.barge_in_rms = barge_in_rms
        self.speech_rms = speech_rms
        self.monotonic = monotonic

        self.state = VoiceState.idle
        self.error: dict[str, str] | None = None
        self.muted = False
        self.mic_on = False
        self.session: LiveSession | None = None
        self.audio: AudioIO | None = None
        self.settings: AppSettings | None = None
        self._tasks: list[asyncio.Task[Any]] = []
        self._uplink: asyncio.Queue[bytes] = asyncio.Queue(maxsize=50)
        self._last_activity = 0.0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "silence_timeout_s": self.settings.ai.interaction_timeout_s if self.settings else 10,
            "muted": self.muted,
            "mic_active": self.mic_on and self.session is not None,  # PRD §11.2 "audio transmitting"
            "error": self.error,
            "model": self.session.model if self.session else None,
        }

    def _set(self, state: VoiceState, error: tuple[str, str] | None = None) -> None:
        self.state = state
        self.error = {"code": error[0], "message": error[1]} if error else None
        hub.publish("voice.state", self.status())

    def _touch(self) -> None:
        self._last_activity = self.monotonic()

    def _fail(self, code: str, message: str) -> None:
        log.warning("voice error %s: %s", code, message)
        self._set(VoiceState.error, (code, message))

    # ------------------------------------------------------------------ session lifecycle
    async def _ensure_session(self) -> bool:
        if self.session is not None:
            return True
        key = self.api_key()
        if not key:
            self._fail("no_api_key", ERROR_TEXT["no_api_key"])
            return False
        self.settings = self.load_settings()
        ai, voice = self.settings.ai, self.settings.voice
        delay = 0.5
        for attempt in range(3):  # reconnect ≤ 3× with backoff (PLAN Phase 4)
            try:
                self.session = await self.connector.connect(
                    api_key=key,
                    models=[ai.model, ai.fallback_model],
                    system=system_prompt(voice.call_me),
                    tools=self.registry.declarations(),
                    voice=voice.gemini_voice,
                )
                break
            except Exception as e:
                err = classify(e)
                if err.code != "offline" or attempt == 2:
                    self._fail(err.code, err.message)
                    return False
                await asyncio.sleep(delay)
                delay *= 2
        if self.audio is None:
            self.audio = self.audio_factory()
        self._touch()
        self._tasks = [
            asyncio.create_task(self._receive_loop(self.session)),
            asyncio.create_task(self._send_loop(self.session)),
            asyncio.create_task(self._watchdog()),
        ]
        return True

    async def _close_session(self) -> None:
        current = asyncio.current_task()
        tasks, self._tasks = self._tasks, []
        for t in tasks:
            if t is not current:
                t.cancel()
        for t in tasks:
            if t is not current:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
        self._stop_mic()
        if self.audio is not None:
            self.audio.clear_playback()
            self.audio.close()
            self.audio = None
        session, self.session = self.session, None
        if session is not None:
            await session.close()
        while not self._uplink.empty():
            self._uplink.get_nowait()

    def _stop_mic(self) -> None:
        if self.mic_on and self.audio is not None:
            self.audio.stop_mic()
        self.mic_on = False

    # ------------------------------------------------------------------ public actions
    async def test_connection(self, api_key: str | None) -> dict[str, Any]:
        """Open and close a session with the given (or stored) key. Never touches the running session."""
        key = api_key or self.api_key()
        if not key:
            return {"ok": False, "code": "no_api_key", "message": ERROR_TEXT["no_api_key"]}
        ai = self.load_settings().ai
        try:
            session = await self.connector.connect(
                api_key=key,
                models=[ai.model, ai.fallback_model],
                system="Connection test.",
                tools=[],
                voice=None,
            )
        except Exception as e:
            err = classify(e)
            return {"ok": False, "code": err.code, "message": err.message}
        await session.close()
        return {"ok": True, "model": session.model}

    async def start(self, *, greet: bool = False) -> dict[str, Any]:
        """Open (or reuse) the session and start listening. `greet` (from the wake word): first say hello
        with today's plan, if the user wants that (Settings → Voice)."""
        async with self._lock:
            if self.muted:
                raise Conflict(ERROR_TEXT["muted"])
            if not await self._ensure_session():
                return self.status()
            if not self.mic_on:
                try:
                    assert self.audio is not None
                    self.audio.start_mic(self._on_mic)
                except AudioError as e:
                    await self._close_session()
                    self._fail("mic_unavailable", str(e))
                    return self.status()
                self.mic_on = True
            self._touch()
            if greet and self.settings is not None and self.settings.voice.greet_on_wake and self.session:
                self._set(VoiceState.processing)  # the greeting is on its way; the user's turn comes after it
                try:
                    await self.session.send_text(GREETING_CUE)
                except Exception as e:
                    await self._close_session()
                    err = classify(e)
                    self._fail(err.code, err.message)
                return self.status()
            self._set(VoiceState.listening)
            return self.status()

    async def send_text(self, text: str) -> dict[str, Any]:
        """A typed turn through the same session and tools (PLAN Phase 4: the panel's text box)."""
        async with self._lock:
            if not await self._ensure_session():
                return self.status()
            assert self.session is not None
            self._touch()
            hub.publish("voice.transcript", {"role": "user", "text": text, "final": True})
            self._set(VoiceState.processing)
            try:
                await self.session.send_text(text)
            except Exception as e:
                await self._close_session()
                err = classify(e)
                self._fail(err.code, err.message)
            return self.status()

    async def stop(self) -> dict[str, Any]:
        """End the interaction: mic off, playback cut, session closed (PRD §11.2 'end an active session')."""
        async with self._lock:
            await self._close_session()
            self._set(VoiceState.muted if self.muted else VoiceState.idle)
            return self.status()

    async def set_muted(self, muted: bool) -> dict[str, Any]:
        self.muted = muted
        if muted:
            return await self.stop()
        self._set(VoiceState.idle)
        return self.status()

    # ------------------------------------------------------------------ audio paths
    def _on_mic(self, frame: bytes) -> None:
        """Event-loop thread. Half-duplex gate with barge-in."""
        if self.session is None or not self.mic_on:
            return
        level = rms(frame)
        if self.audio is not None and self.audio.playing:
            if level < self.barge_in_rms:
                return  # most likely our own voice from the speakers
            self.audio.clear_playback()
            self._interrupted()
        if level >= self.speech_rms:
            self._touch()  # the user is talking: the silence timer only runs while the room is quiet
        with contextlib.suppress(asyncio.QueueFull):
            self._uplink.put_nowait(frame)

    async def _send_loop(self, session: LiveSession) -> None:
        while True:
            frame = await self._uplink.get()
            await session.send_audio(frame)

    async def _receive_loop(self, session: LiveSession) -> None:
        # Gemini ends a turn after every tool call and answers in a new one (Phase 0 finding): a turn that
        # produced only tool calls is not the end of the request, so stay in Processing.
        awaiting_answer = False
        try:
            async for ev in session.events():
                self._touch()
                if isinstance(ev, ToolCalls):
                    awaiting_answer = True
                    self._set(VoiceState.processing)
                    results = []
                    for call_id, name, args in ev.calls:
                        result = self.registry.execute(name, args)
                        hub.publish("voice.tool", {"name": name, "ok": bool(result.get("ok"))})
                        results.append((call_id, name, result))
                    await session.send_tool_results(results)
                elif isinstance(ev, AudioOut):
                    awaiting_answer = False
                    if self.audio is not None and self._replies_enabled():
                        self.audio.play(ev.data)
                        if self.state != VoiceState.speaking:
                            self._set(VoiceState.speaking)
                elif isinstance(ev, Transcript):
                    awaiting_answer = awaiting_answer and ev.role == "user"
                    hub.publish("voice.transcript", {"role": ev.role, "text": ev.text, "final": False})
                elif isinstance(ev, Interrupted):
                    if self.audio is not None:
                        self.audio.clear_playback()
                    self._interrupted()
                elif isinstance(ev, TurnComplete):
                    if awaiting_answer:
                        continue
                    hub.publish("voice.transcript", {"role": "assistant", "text": "", "final": True})
                    if self.audio is not None:
                        await self.audio.drain()
                    self._touch()
                    self._set(VoiceState.listening if self.mic_on else VoiceState.idle)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            err = classify(e)
            await self._close_session()
            self._fail(err.code, err.message)
            return
        # The server ended the session (e.g. its own time limit): back to a clean idle.
        await self._close_session()
        self._set(VoiceState.muted if self.muted else VoiceState.idle)

    def _interrupted(self) -> None:
        """Announce the barge-in, then listen to the new utterance."""
        self._set(VoiceState.interrupted)
        self._set(VoiceState.listening if self.mic_on else VoiceState.idle)

    def _replies_enabled(self) -> bool:
        return self.settings is None or self.settings.voice.voice_replies_enabled

    async def _watchdog(self) -> None:
        """Mic auto-off: close the session after interaction_timeout_s (default 10 s) of silence: no speech
        heard locally or by Gemini, no reply, no tool call. Also give up on a request Gemini never answers
        instead of showing Processing forever."""
        while True:
            await asyncio.sleep(1.0)
            timeout = self.settings.ai.interaction_timeout_s if self.settings else 10
            if self.audio is not None and self.audio.playing:
                continue
            silent_for = self.monotonic() - self._last_activity
            if self.state in (VoiceState.listening, VoiceState.idle) and silent_for > timeout:
                log.info("voice session idle for %ss, closing", timeout)
                asyncio.create_task(self.stop())
                return
            if self.state == VoiceState.processing and silent_for > timeout:
                asyncio.create_task(self._give_up())
                return

    async def _give_up(self) -> None:
        async with self._lock:
            await self._close_session()
            self._fail("no_reply", "Gemini didn't answer. Try again.")


def api_key_lookup(credentials: Any) -> Callable[[], str | None]:
    """Keyring first (PRD §11.1); GEMINI_API_KEY from the environment as a developer fallback."""
    return lambda: credentials.get_api_key() or os.environ.get("GEMINI_API_KEY") or None
