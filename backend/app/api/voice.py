from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.auth import require_token
from app.services.voice_service import VoiceService

router = APIRouter(prefix="/voice", tags=["voice"], dependencies=[Depends(require_token)])


def get_voice(request: Request) -> VoiceService:
    return request.app.state.voice


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class MuteIn(BaseModel):
    muted: bool


class KeyTestIn(BaseModel):
    api_key: str | None = Field(default=None, min_length=20, max_length=200)  # None → test the stored key


# Prebuilt Live API voices (Gemini docs, Live API "voices"). The model may add more; these are stable names.
GEMINI_VOICES = ["Puck", "Charon", "Kore", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr"]


@router.get("")
async def voice_status(voice: VoiceService = Depends(get_voice)) -> dict[str, Any]:
    return voice.status()


@router.get("/wake")
async def wake_status(request: Request) -> dict[str, Any]:
    """Whether "Hey Ziko" is being listened for right now, and why not if it can't be."""
    return request.app.state.wakeword.status()


@router.post("/test")
async def test_connection(body: KeyTestIn, voice: VoiceService = Depends(get_voice)) -> dict[str, Any]:
    """Onboarding / Settings: does this key open a Live session? Never echoes the key."""
    return await voice.test_connection(body.api_key.strip() if body.api_key else None)


@router.get("/devices")
async def input_devices() -> dict[str, Any]:
    """Microphones the user can pick (PRD §3.3). Names are what sounddevice accepts as `device`."""
    try:
        import sounddevice as sd

        names = [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
        default = sd.query_devices(kind="input")["name"]
    except Exception as e:  # no audio subsystem: say so instead of failing the settings screen
        return {"devices": [], "default": None, "error": str(e)}
    return {"devices": list(dict.fromkeys(names)), "default": default, "error": None}


@router.get("/voices")
async def gemini_voices() -> dict[str, Any]:
    return {"voices": GEMINI_VOICES}


@router.post("/start")
async def voice_start(voice: VoiceService = Depends(get_voice)) -> dict[str, Any]:
    """Mic button, wake word or double-click: open the session and listen."""
    return await voice.start()


@router.post("/stop")
async def voice_stop(voice: VoiceService = Depends(get_voice)) -> dict[str, Any]:
    return await voice.stop()


@router.post("/text")
async def voice_text(body: TextIn, voice: VoiceService = Depends(get_voice)) -> dict[str, Any]:
    return await voice.send_text(body.text.strip())


@router.post("/mute")
async def voice_mute(body: MuteIn, voice: VoiceService = Depends(get_voice)) -> dict[str, Any]:
    return await voice.set_muted(body.muted)
