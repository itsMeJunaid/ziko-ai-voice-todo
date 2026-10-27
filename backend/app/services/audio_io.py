"""Microphone in (16 kHz) and speaker out (24 kHz) via sounddevice/PortAudio. Audio is streamed only; nothing
is written to disk (PRD §11.2). Devices that refuse those rates are opened at their own rate and resampled."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from typing import Protocol

import numpy as np

from app.services.gemini_live_service import IN_RATE, OUT_RATE

log = logging.getLogger(__name__)

FRAME_MS = 100


class AudioError(Exception):
    pass


class AudioIO(Protocol):
    def start_mic(self, on_frame: Callable[[bytes], None]) -> None:
        """Deliver 16 kHz int16 mono frames to on_frame on the event-loop thread."""

    def stop_mic(self) -> None: ...
    def play(self, pcm24k: bytes) -> None: ...
    def clear_playback(self) -> None: ...

    @property
    def playing(self) -> bool: ...

    async def drain(self) -> None: ...
    def close(self) -> None: ...


def resample(pcm: bytes, src: int, dst: int) -> bytes:
    if src == dst or not pcm:
        return pcm
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    n = max(1, round(len(x) * dst / src))
    y = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
    return y.astype(np.int16).tobytes()


def rms(pcm: bytes) -> float:
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0


class DeviceAudio:
    def __init__(self, loop: asyncio.AbstractEventLoop, device: str | int | None = None) -> None:
        self.loop = loop
        self.device = device
        self._in = None
        self._out = None
        self._buf = bytearray()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ mic
    def _open_input(self, rate: int, on_frame: Callable[[bytes], None]):
        import sounddevice as sd

        def cb(indata, _frames, _time, status) -> None:
            if status:
                log.debug("mic status: %s", status)
            data = resample(bytes(indata), rate, IN_RATE)
            self.loop.call_soon_threadsafe(on_frame, data)

        s = sd.RawInputStream(
            samplerate=rate,
            channels=1,
            dtype="int16",
            blocksize=rate * FRAME_MS // 1000,
            device=self.device,
            callback=cb,
        )
        s.start()
        return s

    def start_mic(self, on_frame: Callable[[bytes], None]) -> None:
        if self._in is not None:
            return
        import sounddevice as sd

        try:
            self._in = self._open_input(IN_RATE, on_frame)
        except Exception:
            try:
                native = int(sd.query_devices(self.device, "input")["default_samplerate"])
                self._in = self._open_input(native, on_frame)
            except Exception as e:
                raise AudioError(f"Microphone unavailable ({e})") from e

    def stop_mic(self) -> None:
        s, self._in = self._in, None
        if s is not None:
            s.stop()
            s.close()

    # ------------------------------------------------------------------ speaker
    def _out_cb(self, outdata, frames, _time, _status) -> None:
        need = frames * 2
        with self._lock:
            chunk = bytes(self._buf[:need])
            del self._buf[:need]
        outdata[: len(chunk)] = chunk
        outdata[len(chunk) :] = b"\x00" * (need - len(chunk))

    def play(self, pcm24k: bytes) -> None:
        if self._out is None:
            import sounddevice as sd

            try:
                self._out = sd.RawOutputStream(
                    samplerate=OUT_RATE, channels=1, dtype="int16", callback=self._out_cb
                )
                self._out.start()
            except Exception as e:
                raise AudioError(f"Speaker unavailable ({e})") from e
        with self._lock:
            self._buf.extend(pcm24k)

    def clear_playback(self) -> None:
        with self._lock:
            self._buf.clear()

    @property
    def playing(self) -> bool:
        return len(self._buf) > 0

    async def drain(self) -> None:
        while self.playing:
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.15)  # the device's own buffer

    def close(self) -> None:
        self.stop_mic()
        out, self._out = self._out, None
        if out is not None:
            out.stop()
            out.close()
