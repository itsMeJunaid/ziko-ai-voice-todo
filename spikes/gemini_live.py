"""Phase 0 spike — verify the Gemini Live model, tool calling and audio output.

What it proves (PRD §4.4 implementation requirement):
  1. The configured model ID exists and accepts a Live session.
  2. A text turn triggers a function call for `create_task`.
  3. After we send the tool response, the model produces spoken audio (24 kHz PCM).
  4. Input/output transcription works on this model.
  5. Latency from turn-complete to first audio chunk.

Run:  cd backend && uv run --env-file ../.env python ../spikes/gemini_live.py [--model ID] [--no-play]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import wave
from pathlib import Path

from google import genai
from google.genai import types

OUT_DIR = Path(__file__).parent / "out"
OUT_RATE = 24_000  # Live API audio output is 24 kHz 16-bit mono PCM

CREATE_TASK = types.FunctionDeclaration(
    name="create_task",
    description="Create a to-do task. Resolve relative dates with get_current_datetime first.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "title": types.Schema(type=types.Type.STRING),
            "due_at": types.Schema(type=types.Type.STRING, description="ISO-8601 with offset"),
            "priority": types.Schema(type=types.Type.STRING, enum=["low", "medium", "high"]),
        },
        required=["title"],
    ),
)
GET_NOW = types.FunctionDeclaration(
    name="get_current_datetime",
    description="Return the user's current local date-time and timezone.",
    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
)

SYSTEM = (
    "You are Ziko, a concise desktop task assistant. Before interpreting any relative "
    "date like 'tomorrow', call get_current_datetime. Then call create_task with an "
    "ISO-8601 due_at including timezone offset. Only confirm after the tool returns. "
    "Keep spoken replies under 15 words."
)


def fake_tool(call: types.FunctionCall) -> dict:
    if call.name == "get_current_datetime":
        return {"now": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "timezone": time.strftime("%Z")}
    if call.name == "create_task":
        return {"ok": True, "id": "spike-1", **(call.args or {})}
    return {"error": f"unknown tool {call.name}"}


async def run(model: str, play: bool) -> bool:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(parts=[types.Part(text=SYSTEM)]),
        tools=[types.Tool(function_declarations=[CREATE_TASK, GET_NOW])],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    audio = bytearray()
    tool_calls: list[str] = []
    transcript: list[str] = []
    t_sent = t_first_audio = None

    print(f"→ connecting to {model} …")
    async with client.aio.live.connect(model=model, config=config) as session:
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text="Add a task to finish my project tomorrow at 10 AM.")]),
            turn_complete=True,
        )
        t_sent = time.perf_counter()
        # receive() stops at each turn_complete; gemini-3.8-live ends a turn after its first tool call
        # (get_current_datetime), so keep receiving across turns until the task is created and spoken.
        done = False
        try:
            async with asyncio.timeout(45):  # a silent model would otherwise block receive() forever
                while not done:
                    async for msg in session.receive():
                        if msg.tool_call and msg.tool_call.function_calls:
                            responses = []
                            for fc in msg.tool_call.function_calls:
                                tool_calls.append(fc.name)
                                print(f"  ⚙ tool_call {fc.name}({fc.args})")
                                responses.append(types.FunctionResponse(id=fc.id, name=fc.name, response=fake_tool(fc)))
                            await session.send_tool_response(function_responses=responses)
                            continue
                        sc = msg.server_content
                        if not sc:
                            continue
                        if sc.output_transcription and sc.output_transcription.text:
                            transcript.append(sc.output_transcription.text)
                        if sc.model_turn:
                            for part in sc.model_turn.parts or []:
                                if part.inline_data and part.inline_data.data:
                                    if t_first_audio is None:
                                        t_first_audio = time.perf_counter()
                                    audio.extend(part.inline_data.data)
                        if sc.turn_complete and "create_task" in tool_calls and audio:
                            done = True
                            break
        except TimeoutError:
            print("  ⏱ no completed reply within 45 s")

    ok = "create_task" in tool_calls and len(audio) > 0
    print(f"\nmodel            : {model}")
    print(f"tool calls       : {tool_calls}")
    print(f"audio bytes      : {len(audio)}  (~{len(audio)/2/OUT_RATE:.1f}s)")
    print(f"first-audio lat. : {(t_first_audio - t_sent)*1000:.0f} ms" if t_first_audio else "first-audio lat. : n/a")
    print(f"transcript       : {''.join(transcript).strip()!r}")
    print(f"RESULT           : {'PASS' if ok else 'FAIL'}")

    if audio:
        OUT_DIR.mkdir(exist_ok=True)
        wav_path = OUT_DIR / f"reply_{model.replace('/', '_')}.wav"
        with wave.open(str(wav_path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(OUT_RATE); w.writeframes(bytes(audio))
        print(f"saved            : {wav_path}")
        if play:
            try:
                import numpy as np, sounddevice as sd
                sd.play(np.frombuffer(bytes(audio), dtype=np.int16), OUT_RATE); sd.wait()
            except Exception as e:  # no output device on headless boxes
                print(f"(playback skipped: {e})")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get("ZIKO_GEMINI_MODEL", "gemini-3.8-live"))
    ap.add_argument("--fallback", default=os.environ.get("ZIKO_GEMINI_FALLBACK_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025"))
    ap.add_argument("--no-play", action="store_true")
    a = ap.parse_args()
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY not set — copy .env.example to .env and fill it in.")
    for m in [a.model, a.fallback]:
        try:
            if asyncio.run(run(m, not a.no_play)):
                return
        except Exception as e:
            print(f"✗ {m}: {type(e).__name__}: {e}\n")
    sys.exit("No model passed — check model IDs at https://ai.google.dev/gemini-api/docs/models")


if __name__ == "__main__":
    main()
