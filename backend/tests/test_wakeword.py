"""Wake word: when the mic listens, hand-off to the conversation, recovery (PRD §4.2), and the real model."""

from __future__ import annotations

import asyncio
import glob
import wave
from pathlib import Path

import numpy as np
import pytest

from app.schemas.settings import AppSettings
from app.services.wakeword import service as svc
from app.services.wakeword.detector import FRAME, SAMPLE_RATE
from app.ws.events import hub

REPO = Path(__file__).resolve().parents[2]


class FakeVoice:
    def __init__(self) -> None:
        self.muted = False
        self.session = None
        self.starts = 0

    async def start(self, *, greet=False):
        self.starts += 1
        self.greeted = greet
        self.session = object()


class FakeStream:
    def __init__(self, on_frame) -> None:
        self.on_frame = on_frame
        self.active = True
        self.closed = False

    def close(self) -> None:
        self.closed = True
        self.active = False


class FakeDetector:
    def __init__(self, threshold: float) -> None:
        self.threshold = threshold
        self.next: list[float | None] = []

    def feed(self, frame):
        return self.next.pop(0) if self.next else None

    def reset(self) -> None:
        pass


@pytest.fixture
async def world():
    settings = AppSettings()
    voice = FakeVoice()
    streams: list[FakeStream] = []
    detectors: list[FakeDetector] = []

    def stream_factory(device, on_frame):
        if getattr(stream_factory, "fail", False):
            raise OSError("no input device")
        s = FakeStream(on_frame)
        streams.append(s)
        return s

    def detector_factory(t):
        d = FakeDetector(t)
        detectors.append(d)
        return d

    ww = svc.WakeWordService(
        voice=voice,
        settings=lambda: settings,
        detector_factory=detector_factory,
        stream_factory=stream_factory,
    )
    ww.loop = asyncio.get_running_loop()
    yield ww, settings, voice, streams, detectors, stream_factory
    ww.close()


FRAME_PCM = np.zeros(FRAME, dtype=np.int16)


async def settle():
    for _ in range(10):
        await asyncio.sleep(0.01)


async def test_listens_only_when_enabled_unmuted_and_idle(world):
    ww, settings, voice, streams, *_ = world
    ww.refresh()
    assert ww.listening and len(streams) == 1
    settings.voice.wake_word_enabled = False
    ww.refresh()
    assert not ww.listening and streams[0].closed
    settings.voice.wake_word_enabled = True
    voice.muted = True
    ww.refresh()
    assert not ww.listening  # PRD §4.2: mute stops listening
    voice.muted = False
    voice.session = object()
    ww.refresh()
    assert not ww.listening  # the conversation owns the mic


async def test_a_hit_hands_the_mic_to_the_conversation_once(world):
    ww, _, voice, streams, detectors, _ = world
    q = asyncio.Queue()
    hub._clients[q] = q
    try:
        ww.refresh()
        detectors[0].next = [0.93, 0.95]
        streams[0].on_frame(FRAME_PCM)
        streams[0].on_frame(FRAME_PCM)  # same utterance: must not start twice
        await settle()
        assert voice.starts == 1 and voice.greeted and streams[0].closed and not ww.listening
        events = [q.get_nowait() for _ in range(q.qsize())]
        assert {"type": "voice.wake", "payload": {"score": 0.93}} in events
    finally:
        hub._clients.pop(q, None)
    voice.session = None  # conversation ended
    ww._last_hit -= svc.REFRACTORY_S
    ww.refresh()
    assert ww.listening and len(streams) == 2


async def test_restarts_a_dead_stream_and_retries_a_missing_mic(world, monkeypatch):
    ww, _, _, streams, _, stream_factory = world
    ww.refresh()
    streams[0].active = False  # device unplugged
    ww.refresh()
    assert len(streams) == 2 and ww.listening
    ww.close()
    stream_factory.fail = True
    ww.refresh()
    assert not ww.listening and "no input device" in ww.status()["error"]
    stream_factory.fail = False
    ww.refresh()
    assert not ww.listening  # waits RETRY_S before trying again
    monkeypatch.setattr(svc, "RETRY_S", 0)
    ww._retry_at = 0
    ww.refresh()
    assert ww.listening and ww.status()["error"] is None


async def test_threshold_change_rebuilds_the_detector(world):
    ww, settings, _, _, detectors, _ = world
    ww.refresh()
    settings.voice.wake_word_threshold = 0.9
    ww.refresh()
    ww.refresh()
    assert [d.threshold for d in detectors] == [0.8, 0.9] and ww.listening


def test_old_settings_get_the_tuned_threshold_once():
    from app.services.settings_service import _upgrade

    assert _upgrade({"voice": {"wake_word_threshold": 0.5}})["voice"]["wake_word_threshold"] == 0.8
    chosen = {"version": 2, "voice": {"wake_word_threshold": 0.5}}  # the user picked 0.5 later: keep it
    assert _upgrade(chosen)["voice"]["wake_word_threshold"] == 0.5
    v2 = _upgrade({"version": 2, "ai": {"interaction_timeout_s": 20}, "appearance": {"dot_size": 56}})
    assert v2["ai"]["interaction_timeout_s"] == 10 and v2["appearance"]["dot_size"] == 44  # v3 defaults
    mine = {"version": 3, "ai": {"interaction_timeout_s": 20}}  # chosen after v3: keep it
    assert _upgrade(mine)["ai"]["interaction_timeout_s"] == 20


HITS = sorted(glob.glob(str(REPO / "spikes/out/hits/hit_*.wav")))


@pytest.mark.skipif(len(HITS) < 10, reason="Phase 0 recordings not present")
def test_real_model_on_real_recordings():
    """The shipped model + detector on 10 real "Hey Ziko" clips and on Gemini speech (PLAN: ≥ 90% hits)."""
    from app.services.audio_io import resample
    from app.services.wakeword.detector import LiveKitDetector

    d = LiveKitDetector(threshold=AppSettings().voice.wake_word_threshold)

    def fires(path: str) -> bool:
        with wave.open(path) as w:
            pcm = np.frombuffer(
                resample(w.readframes(w.getnframes()), w.getframerate(), SAMPLE_RATE), np.int16
            )
        pad = np.zeros(SAMPLE_RATE, np.int16)
        x = np.concatenate([pad, pcm, pad])
        d.reset()
        return any(d.feed(x[i : i + FRAME]) is not None for i in range(0, len(x) - FRAME, FRAME))

    assert sum(fires(p) for p in HITS) >= 9
    for speech in glob.glob(str(REPO / "spikes/out/reply_*.wav")):
        assert not fires(speech), speech
