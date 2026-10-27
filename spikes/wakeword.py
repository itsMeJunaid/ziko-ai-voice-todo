"""Phase 0 spike — Porcupine wake-word detection on the real microphone.

Proves (PRD §4.2): local detection, latency, hit rate and idle false positives.
Say "Hey Ziko" ~20 times; then stay silent / talk normally to measure false positives.

Run:  cd backend && uv run --env-file ../.env python ../spikes/wakeword.py [--seconds 120] [--sensitivity 0.6]
If ZIKO_WAKEWORD_PPN is missing, falls back to the built-in "jarvis" keyword so the audio
pipeline itself can be verified before the custom model is trained.
"""
from __future__ import annotations

import argparse
import os
import queue
import sys
import time

import numpy as np
import pvporcupine
import sounddevice as sd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--sensitivity", type=float, default=0.6)
    ap.add_argument("--device", type=int, default=None, help="sounddevice input index (see --list)")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        print(sd.query_devices()); return

    key = os.environ.get("PICOVOICE_ACCESS_KEY")
    if not key:
        sys.exit("PICOVOICE_ACCESS_KEY not set — free key at https://console.picovoice.ai")
    ppn = os.environ.get("ZIKO_WAKEWORD_PPN", "")
    if ppn and os.path.exists(ppn):
        porcupine = pvporcupine.create(access_key=key, keyword_paths=[ppn], sensitivities=[a.sensitivity])
        label = f"custom model {os.path.basename(ppn)}"
    else:
        porcupine = pvporcupine.create(access_key=key, keywords=["jarvis"], sensitivities=[a.sensitivity])
        label = "built-in 'jarvis' (custom .ppn not found — train 'Hey Ziko' in the Picovoice console)"

    q: queue.Queue[np.ndarray] = queue.Queue()
    def cb(indata, frames, t, status):
        if status: print("audio status:", status, file=sys.stderr)
        q.put(indata[:, 0].copy())

    hits = 0; last_hit = 0.0; frames = 0; t0 = time.perf_counter()
    print(f"Listening for {label} | rate={porcupine.sample_rate} frame={porcupine.frame_length} | {a.seconds}s | Ctrl+C to stop")
    with sd.InputStream(samplerate=porcupine.sample_rate, blocksize=porcupine.frame_length,
                        channels=1, dtype="int16", device=a.device, callback=cb):
        try:
            while time.perf_counter() - t0 < a.seconds:
                pcm = q.get(timeout=1)
                frames += 1
                if porcupine.process(pcm) >= 0:
                    now = time.perf_counter()
                    if now - last_hit < 2.0:   # refractory window — PRD: no repeated activations per utterance
                        continue
                    last_hit = now; hits += 1
                    print(f"  ✔ WAKE #{hits} at {now - t0:6.1f}s")
        except KeyboardInterrupt:
            pass
    porcupine.delete()
    dur = time.perf_counter() - t0
    print(f"\nframes={frames} ({frames*porcupine.frame_length/porcupine.sample_rate:.0f}s audio) hits={hits} over {dur:.0f}s")
    print("Record in README: hits/20 utterances, false positives during idle minutes, approx CPU% from Task Manager.")


if __name__ == "__main__":
    main()
