"""Fakes for the voice stack: a scripted Gemini Live connector, recorded audio, and a hub listener."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.ws.events import hub

LOUD = (b"\xff\x7f\x01\x80") * 800  # full-scale square wave: certainly the user talking
QUIET = b"\x10\x00" * 1600


class FakeSession:
    model = "fake-live"

    def __init__(self) -> None:
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.audio: list[bytes] = []
        self.texts: list[str] = []
        self.tool_results: list = []
        self.closed = False

    async def send_audio(self, pcm: bytes) -> None:
        self.audio.append(pcm)

    async def send_text(self, text: str) -> None:
        self.texts.append(text)

    async def send_tool_results(self, results) -> None:
        self.tool_results.extend(results)

    async def events(self) -> AsyncIterator:
        while True:
            ev = await self.inbox.get()
            if ev is None:
                return
            if isinstance(ev, Exception):
                raise ev
            yield ev

    async def close(self) -> None:
        self.closed = True


class FakeConnector:
    def __init__(self) -> None:
        self.failures: list[Exception] = []
        self.calls: list[dict] = []
        self.sessions: list[FakeSession] = []

    async def connect(self, **kw) -> FakeSession:
        self.calls.append(kw)
        if self.failures:
            raise self.failures.pop(0)
        s = FakeSession()
        self.sessions.append(s)
        return s


class FakeAudio:
    def __init__(self) -> None:
        self.on_frame = None
        self.played = bytearray()
        self.playing_flag = False
        self.cleared = 0
        self.closed = False

    def start_mic(self, on_frame) -> None:
        self.on_frame = on_frame

    def stop_mic(self) -> None:
        self.on_frame = None

    def play(self, pcm: bytes) -> None:
        self.played.extend(pcm)

    def clear_playback(self) -> None:
        self.cleared += 1
        self.playing_flag = False

    @property
    def playing(self) -> bool:
        return self.playing_flag

    async def drain(self) -> None:
        self.playing_flag = False

    def close(self) -> None:
        self.closed = True


class Events:
    """Collects hub events like a connected UI would."""

    def __init__(self) -> None:
        self.q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.key = object()

    def __enter__(self):
        hub._clients[self.key] = self.q
        return self

    def __exit__(self, *_):
        hub._clients.pop(self.key, None)

    def drain(self, type_: str) -> list[dict]:
        out = []
        while not self.q.empty():
            e = self.q.get_nowait()
            if e["type"] == type_:
                out.append(e["payload"])
        return out


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0.01)
