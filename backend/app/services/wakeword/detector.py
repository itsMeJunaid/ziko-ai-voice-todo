"""Local "Hey Ziko" detection (PRD §4.2). Runs entirely on this machine; no audio leaves it while idle.

LiveKit WakeWordModel over the model trained in Phase 0 (`app/assets/hey_ziko.onnx`). `predict()` is
stateless and wants ~2 s of audio, so we keep a rolling 2 s window and score it every 240 ms: ~23 ms per call
(measured), well under 10% of one core. Detection latency stays under a second.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Protocol

import numpy as np

SAMPLE_RATE = 16_000
FRAME = 1280  # 80 ms
WINDOW = 2 * SAMPLE_RATE
HOP_FRAMES = 3  # score every 240 ms


def default_model_path() -> Path:
    if hasattr(sys, "_MEIPASS"):  # PyInstaller bundle: data files unpack under the bundle root
        return Path(sys._MEIPASS) / "app" / "assets" / "hey_ziko.onnx"
    return Path(__file__).resolve().parents[2] / "assets" / "hey_ziko.onnx"


class WakeWordDetector(Protocol):
    def feed(self, frame: np.ndarray) -> float | None:
        """One 80 ms int16 frame. Returns the score when the wake word is detected, else None."""

    def reset(self) -> None: ...


class LiveKitDetector:
    def __init__(
        self, threshold: float, model_path: Path | None = None, hop_frames: int = HOP_FRAMES
    ) -> None:
        from livekit.wakeword import WakeWordModel
        from onnxruntime import SessionOptions

        path = model_path or default_model_path()
        if not path.exists():
            raise FileNotFoundError(f"wake word model missing: {path}")
        # onnxruntime defaults to one *spinning* thread per core: ~1800% CPU while idle on a 20-core box
        # (measured in Phase 0). One non-spinning thread is faster for this tiny model and costs ~6%.
        opts = SessionOptions()
        opts.intra_op_num_threads = opts.inter_op_num_threads = 1
        opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.model = WakeWordModel(models=[str(path)], sess_options=opts)
        self.name = path.stem
        self.threshold = threshold
        self.hop = hop_frames
        self.reset()

    def reset(self) -> None:
        self.ring = np.zeros(WINDOW, dtype=np.int16)
        self.frames = 0

    def score(self) -> float:
        scores = self.model.predict(self.ring)
        return float(scores.get(self.name, max(scores.values(), default=0.0)))

    def feed(self, frame: np.ndarray) -> float | None:
        n = len(frame)
        self.ring = np.concatenate((self.ring[n:], frame.astype(np.int16, copy=False)))
        self.frames += 1
        if self.frames % self.hop:
            return None
        s = self.score()
        return s if s >= self.threshold else None
