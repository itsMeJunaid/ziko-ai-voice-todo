"""Gemini Live behind a small, testable seam (PRD §4.4). The SDK's message stream becomes a few plain events;
the voice service never touches `google.genai` types, and tests swap in a fake connector.

Phase 0 findings applied: `receive()` ends at every turn_complete and gemini-3.8-live ends a turn after each
tool call, so the event stream loops `receive()` until the connection really closes.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol

log = logging.getLogger(__name__)

IN_RATE = 16_000  # Live API input: 16-bit mono PCM
OUT_RATE = 24_000  # Live API output


# ---------------------------------------------------------------------- events
@dataclass
class ToolCalls:
    calls: list[tuple[str, str, dict[str, Any]]]  # (call id, tool name, args)


@dataclass
class AudioOut:
    data: bytes


@dataclass
class Transcript:
    role: Literal["user", "assistant"]
    text: str


@dataclass
class TurnComplete:
    pass


@dataclass
class Interrupted:
    """The server heard the user talk over the reply (barge-in): stop playback now."""


LiveEvent = ToolCalls | AudioOut | Transcript | TurnComplete | Interrupted


class LiveError(Exception):
    """A failure the UI can explain. code: invalid_key | offline | model_unavailable | error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def classify(e: BaseException) -> LiveError:
    if isinstance(e, LiveError):
        return e
    text = f"{type(e).__name__}: {e}"
    low = text.lower()
    if "api key" in low or "api_key" in low or "permission" in low or "unauthenticated" in low:
        return LiveError("invalid_key", "Gemini rejected the API key. Check it in Settings.")
    if "not found" in low or "not supported" in low or "is not available" in low:
        return LiveError("model_unavailable", "The configured Gemini Live model is not available.")
    if isinstance(e, OSError | TimeoutError) or "connection" in low or "timed out" in low:
        return LiveError("offline", "Can't reach Gemini. Check the internet connection.")
    return LiveError("error", f"Gemini error ({type(e).__name__}).")


# ---------------------------------------------------------------------- seam
class LiveSession(Protocol):
    model: str

    async def send_audio(self, pcm16k: bytes) -> None: ...
    async def send_text(self, text: str) -> None: ...
    async def send_tool_results(self, results: list[tuple[str, str, dict[str, Any]]]) -> None: ...
    def events(self) -> AsyncIterator[LiveEvent]: ...
    async def close(self) -> None: ...


class LiveConnector(Protocol):
    async def connect(
        self, *, api_key: str, models: list[str], system: str, tools: list[dict[str, Any]], voice: str | None
    ) -> LiveSession: ...


# ---------------------------------------------------------------------- Gemini implementation
class GeminiSession:
    def __init__(self, model: str, session: Any, stack: contextlib.AsyncExitStack) -> None:
        self.model = model
        self._s = session
        self._stack = stack

    async def send_audio(self, pcm16k: bytes) -> None:
        from google.genai import types

        blob = types.Blob(data=pcm16k, mime_type=f"audio/pcm;rate={IN_RATE}")
        await self._s.send_realtime_input(audio=blob)

    async def send_text(self, text: str) -> None:
        from google.genai import types

        await self._s.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=text)]), turn_complete=True
        )

    async def send_tool_results(self, results: list[tuple[str, str, dict[str, Any]]]) -> None:
        from google.genai import types

        await self._s.send_tool_response(
            function_responses=[types.FunctionResponse(id=i, name=n, response=r) for i, n, r in results]
        )

    async def events(self) -> AsyncIterator[LiveEvent]:
        while True:
            got_any = False
            async for msg in self._s.receive():
                got_any = True
                if msg.tool_call and msg.tool_call.function_calls:
                    calls = msg.tool_call.function_calls
                    yield ToolCalls([(fc.id, fc.name, dict(fc.args or {})) for fc in calls])
                sc = msg.server_content
                if not sc:
                    continue
                if sc.interrupted:
                    yield Interrupted()
                if sc.input_transcription and sc.input_transcription.text:
                    yield Transcript("user", sc.input_transcription.text)
                if sc.output_transcription and sc.output_transcription.text:
                    yield Transcript("assistant", sc.output_transcription.text)
                if sc.model_turn:
                    for part in sc.model_turn.parts or []:
                        if part.inline_data and part.inline_data.data:
                            yield AudioOut(part.inline_data.data)
                if sc.turn_complete:
                    yield TurnComplete()
            if not got_any:  # receive() returned immediately: the connection is gone
                return

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self._stack.aclose()


class GeminiLiveConnector:
    async def connect(
        self, *, api_key: str, models: list[str], system: str, tools: list[dict[str, Any]], voice: str | None
    ) -> LiveSession:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(parts=[types.Part(text=system)]),
            tools=[types.Tool(function_declarations=[types.FunctionDeclaration(**t) for t in tools])],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            speech_config=(
                types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                    )
                )
                if voice
                else None
            ),
        )
        last: LiveError | None = None
        for model in models:  # configured model, then the fallback (PLAN §0)
            stack = contextlib.AsyncExitStack()
            try:
                session = await stack.enter_async_context(client.aio.live.connect(model=model, config=config))
                log.info("gemini live connected model=%s", model)
                return GeminiSession(model, session, stack)
            except Exception as e:
                await stack.aclose()
                last = classify(e)
                log.warning("gemini live connect failed model=%s: %s", model, last.code)
                if last.code in ("invalid_key", "offline"):
                    break  # the next model would fail the same way
        raise last or LiveError("error", "No Gemini model configured")
