"""Idle listening for "Hey Ziko" (PRD §4.2, PLAN Phase 5).

The wake-word mic is on only while it should be: wake word enabled, microphone not muted, and no voice
session running (the conversation owns the mic then). Audio goes PortAudio thread → queue → one detector
thread, so scoring never blocks the event loop. On a hit: `voice.wake` is published (the dot pulses and opens
the panel), the listener stops, and the voice session starts; when the session ends, listening resumes.
A supervisor re-checks every second, which also restarts the mic after a device change or disconnect.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

import numpy as np

from app.schemas.settings import AppSettings
from app.services.wakeword.detector import FRAME, SAMPLE_RATE, WakeWordDetector
from app.ws.events import hub

log = logging.getLogger(__name__)

REFRACTORY_S = 2.0  # one activation per utterance (PRD §4.2)
RETRY_S = 5.0


class MicStream(Protocol):
    @property
    def active(self) -> bool: ...

    def close(self) -> None: ...


def open_device_stream(device: Any, on_frame: Callable[[np.ndarray], None]) -> MicStream:
    import sounddevice as sd

    def cb(indata, _frames, _time, _status) -> None:
        on_frame(indata[:, 0].copy())

    s = sd.InputStream(
        samplerate=SAMPLE_RATE, blocksize=FRAME, channels=1, dtype="int16", device=device, callback=cb
    )
    s.start()
    return s


class WakeWordService:
    def __init__(
        self,
        *,
        voice: Any,  # VoiceService (status(), start(), session, muted)
        settings: Callable[[], AppSettings],
        detector_factory: Callable[[float], WakeWordDetector],
        stream_factory: Callable[[Any, Callable[[np.ndarray], None]], MicStream] = open_device_stream,
    ) -> None:
        self.voice = voice
        self.load_settings = settings
        self.detector_factory = detector_factory
        self.stream_factory = stream_factory
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stream: MicStream | None = None
        self.detector: WakeWordDetector | None = None
        self.error: str | None = None
        self._frames: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=200)
        self._worker: threading.Thread | None = None
        self._last_hit = 0.0
        self._retry_at = 0.0
        self._threshold: float | None = None

    @property
    def listening(self) -> bool:
        return self.stream is not None

    def status(self) -> dict[str, Any]:
        return {"listening": self.listening, "error": self.error}

    # ------------------------------------------------------------------ desired state
    def _should_listen(self, s: AppSettings) -> bool:
        return s.voice.wake_word_enabled and not self.voice.muted and self.voice.session is None

    def refresh(self) -> None:
        """Bring the mic in line with the desired state. Safe to call often (event loop thread)."""
        s = self.load_settings()
        want = self._should_listen(s)
        if want and self.stream is not None and not self.stream.active:
            log.warning("wake word mic stopped (device change?) — restarting")
            self._stop()
        if want and self.stream is not None and self._threshold != s.voice.wake_word_threshold:
            self._stop()  # threshold changed in Settings
        if want and self.stream is None and time.monotonic() >= self._retry_at:
            self._start(s)
        elif not want and self.stream is not None:
            self._stop()

    def _start(self, s: AppSettings) -> None:
        try:
            if self.detector is None or self._threshold != s.voice.wake_word_threshold:
                self.detector = self.detector_factory(s.voice.wake_word_threshold)
                self._threshold = s.voice.wake_word_threshold
            self.detector.reset()
            self._frames = queue.Queue(maxsize=200)
            self._worker = threading.Thread(target=self._detect_loop, args=(self._frames,), daemon=True)
            self._worker.start()
            q = self._frames
            self.stream = self.stream_factory(s.voice.mic_device, lambda f: _offer(q, f))
            self._set_error(None)
            log.info("wake word listening (threshold %.2f)", s.voice.wake_word_threshold)
        except Exception as e:
            self._stop()
            self._retry_at = time.monotonic() + RETRY_S
            self._set_error(f"Wake word unavailable: {e}")

    def _stop(self) -> None:
        stream, self.stream = self.stream, None
        if stream is not None:
            try:
                stream.close()
            except Exception:
                log.debug("closing wake word stream failed", exc_info=True)
        if self._worker is not None:
            _offer(self._frames, None)  # wake the worker so it exits
            self._worker = None

    def _set_error(self, message: str | None) -> None:
        if message != self.error:
            self.error = message
            if message:
                log.warning(message)
            hub.publish("wakeword.state", self.status())

    # ------------------------------------------------------------------ detection
    def _detect_loop(self, frames: queue.Queue[np.ndarray | None]) -> None:
        detector = self.detector
        while True:
            frame = frames.get()
            if frame is None or detector is None:
                return
            score = detector.feed(frame)
            if score is not None and self.loop is not None:
                self.loop.call_soon_threadsafe(self._on_hit, score)

    def _on_hit(self, score: float) -> None:
        now = time.monotonic()
        if now - self._last_hit < REFRACTORY_S or self.stream is None:
            return
        self._last_hit = now
        log.info("wake word detected (score %.2f)", score)
        self._stop()  # hand the microphone to the conversation
        hub.publish("voice.wake", {"score": round(score, 2)})
        asyncio.create_task(self._start_voice())

    async def _start_voice(self) -> None:
        try:
            await self.voice.start(greet=True)  # "Hi Boss! …" with today's plan, then listen
        except Exception as e:  # e.g. muted between the hit and now; listening resumes via refresh
            log.info("voice start after wake word refused: %s", e)
        self.refresh()

    # ------------------------------------------------------------------ lifecycle
    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        while True:
            try:
                self.refresh()
            except Exception:
                log.exception("wake word supervisor tick failed")
            await asyncio.sleep(1.0)

    def close(self) -> None:
        self._stop()


def _offer(q: queue.Queue[np.ndarray | None], item: np.ndarray | None) -> None:
    try:
        q.put_nowait(item)
    except queue.Full:
        pass  # detector is behind: dropping a frame beats queueing seconds of stale audio
