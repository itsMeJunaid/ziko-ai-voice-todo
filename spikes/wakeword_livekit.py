"""Phase 0 spike — LiveKit wakeword ("Hey Ziko") on the real microphone. Open source, no key.

Proves (PRD §4.2): local detection, latency, hit rate, idle false positives, idle CPU.
Say "Hey Ziko" ~20 times; then stay silent / talk normally to measure false positives.

Train the model first (one-off):
    uv tool install "livekit-wakeword[train,eval,export]"
    livekit-wakeword setup
    livekit-wakeword run spikes/hey_ziko.yaml        → spikes/out/hey_ziko/hey_ziko.onnx

Run:  cd backend && uv run --env-file ../.env python ../spikes/wakeword_livekit.py [--seconds 120] [--threshold 0.8]
"""
from __future__ import annotations

import argparse
import os
import queue
import sys
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
from livekit.wakeword import WakeWordModel
from onnxruntime import SessionOptions

SAMPLE_RATE = 16_000
FRAME = 1280            # 80 ms mic frames
WINDOW = 2 * SAMPLE_RATE  # WakeWordModel.predict() is STATELESS: it wants ~2 s of audio every call
# Measured 2026-10-26 on the dev box: mel + 16 embeddings ≈ 23 ms per call. Calling every 80 ms frame
# would burn ~29% of a core while idle; every 3rd frame (240 ms hop) ≈ 9%. Detection latency stays < 1 s.
DEFAULT_HOP_FRAMES = 3


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get("ZIKO_WAKEWORD_ONNX", "spikes/out/hey_ziko/hey_ziko.onnx"))
    ap.add_argument("--threshold", type=float, default=float(os.environ.get("ZIKO_WAKEWORD_THRESHOLD", "0.8")))
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--debounce", type=float, default=2.0, help="refractory seconds after a hit (PRD: one activation per utterance)")
    ap.add_argument("--hop", type=int, default=DEFAULT_HOP_FRAMES, help="run predict every N 80 ms frames (CPU vs latency)")
    ap.add_argument("--device", type=int, default=None, help="sounddevice input index (see --list)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--guided", type=int, default=0, metavar="N",
                    help="print N 'SAY IT NOW' cues (every --gap s), then stay silent; scores hits/misses/false positives")
    ap.add_argument("--gap", type=float, default=5.0, help="seconds between guided cues")
    ap.add_argument("--vad-rms", type=float, default=500.0,
                    help="int16 RMS per 80 ms frame that counts as speech, for utterance-based scoring")
    ap.add_argument("--save-hits", default="spikes/out/hits", help="dir for a 2 s WAV per detection ('' to disable)")
    a = ap.parse_args()
    if a.list:
        print(sd.query_devices()); return

    model_path = Path(a.model)
    if not model_path.is_absolute() and not model_path.exists():  # .env paths are relative to the repo root
        model_path = Path(__file__).resolve().parent.parent / model_path
    if not model_path.exists():
        sys.exit(f"model not found: {model_path}\nTrain it: livekit-wakeword run spikes/hey_ziko.yaml")
    # onnxruntime defaults to one spinning thread per core: ~1800% CPU while idle-listening on a 20-core box.
    # A single non-spinning thread is faster for these tiny models (14 vs 27 ms/call) and costs ~6% of one core.
    opts = SessionOptions()
    opts.intra_op_num_threads = opts.inter_op_num_threads = 1
    opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
    model = WakeWordModel(models=[str(model_path)], sess_options=opts)
    name = model_path.stem

    q: queue.Queue[np.ndarray] = queue.Queue()
    def cb(indata, frames, t, status):
        if status: print("audio status:", status, file=sys.stderr)
        q.put(indata[:, 0].copy())

    hits_dir = None
    if a.save_hits:
        hits_dir = Path(a.save_hits)
        if not hits_dir.is_absolute():
            hits_dir = Path(__file__).resolve().parent.parent / hits_dir
        hits_dir.mkdir(parents=True, exist_ok=True)
        for old in hits_dir.glob("hit_*.wav"):
            old.unlink()
    cues = [3.0 + i * a.gap for i in range(a.guided)]  # seconds after start
    next_cue = 0; hit_times: list[float] = []
    # Utterance segmentation by frame energy: people don't speak exactly on cue, so recall is scored
    # against what was actually said (speech bursts), and a detection with no speech nearby is a false positive.
    utterances: list[list[float]] = []  # [onset, last voiced] seconds
    frame_s = FRAME / SAMPLE_RATE

    ring = np.zeros(WINDOW, dtype=np.int16)  # rolling 2 s window
    hits = 0; last_hit = -1e9; frames = 0; peak = 0.0; t0 = time.perf_counter(); cpu0 = time.process_time()
    print(f"Listening for '{name}' thr={a.threshold} | {SAMPLE_RATE} Hz, 2 s window, predict every {a.hop*80} ms | {a.seconds}s | Ctrl+C to stop")
    with sd.InputStream(samplerate=SAMPLE_RATE, blocksize=FRAME, channels=1, dtype="int16", device=a.device, callback=cb):
        try:
            while time.perf_counter() - t0 < a.seconds:
                pcm = q.get(timeout=1)
                frames += 1
                if next_cue < len(cues) and time.perf_counter() - t0 >= cues[next_cue]:
                    next_cue += 1
                    print(f"  >>> SAY IT NOW ({next_cue}/{len(cues)})", flush=True)
                    if next_cue == len(cues):
                        print(f"  >>> now stay SILENT until the end ({a.seconds - cues[-1]:.0f} s)", flush=True)
                ring = np.concatenate((ring[len(pcm):], pcm))
                if np.sqrt(np.mean(pcm.astype(np.float32) ** 2)) >= a.vad_rms:
                    ts = frames * frame_s
                    if utterances and ts - utterances[-1][1] <= 0.6:
                        utterances[-1][1] = ts
                    else:
                        utterances.append([ts, ts])
                if frames % a.hop:
                    continue
                scores = model.predict(ring)
                score = scores.get(name, max(scores.values(), default=0.0))
                peak = max(peak, score)
                if score >= a.threshold:
                    now = time.perf_counter()
                    if now - last_hit < a.debounce:
                        continue
                    last_hit = now; hits += 1
                    hit_times.append(frames * frame_s)
                    print(f"  ✔ WAKE #{hits} at {now - t0:6.1f}s  score={score:.2f}", flush=True)
                    if hits_dir:
                        with wave.open(str(hits_dir / f"hit_{hits:02d}_{now - t0:05.1f}s_{score:.2f}.wav"), "wb") as w:
                            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE); w.writeframes(ring.tobytes())
        except KeyboardInterrupt:
            pass
    dur = time.perf_counter() - t0; cpu = time.process_time() - cpu0
    print(f"\nframes={frames} ({frames*FRAME/SAMPLE_RATE:.0f}s audio) hits={hits} peak_score={peak:.2f} over {dur:.0f}s")
    print(f"approx CPU: {100*cpu/dur:.1f}% of one core while listening (hop={a.hop*80} ms)")
    spoken = [u for u in utterances if u[1] - u[0] >= 0.25]  # ignore clicks / bumps
    if spoken:
        # a detection belongs to an utterance if it fires between its onset and 2.5 s after it ends
        got = [u for u in spoken if any(u[0] <= h <= u[1] + 2.5 for h in hit_times)]
        fps = [h for h in hit_times if not any(u[0] <= h <= u[1] + 2.5 for u in utterances)]
        print(f"BY SPEECH: {len(got)}/{len(spoken)} utterances detected, {len(fps)} false positive(s) "
              f"(detections with no speech) {['%.1fs' % f for f in fps]}  [vad-rms={a.vad_rms:.0f}]")
        print("  note: every speech burst counts as an utterance, so talking other words lowers this number")
    if cues:
        # a hit counts for a cue if it lands within 3 s after it (speech + 2 s window + hop)
        matched = set(); fps = []
        for h in hit_times:
            c = next((i for i, c in enumerate(cues) if i not in matched and 0 <= h - c <= 3.0), None)
            (matched.add(c) if c is not None else fps.append(h))
        silent = a.seconds - (cues[-1] + 3.0)
        print(f"BY CUE:  {len(matched)}/{len(cues)} detected, {len(cues) - len(matched)} missed, "
              f"{len(fps)} false positive(s) {['%.1fs' % f for f in fps]} ({silent:.0f} s of silence after the cues)")
    if hits_dir and hits:
        print(f"saved {hits} detection clip(s) to {hits_dir}")


if __name__ == "__main__":
    main()
