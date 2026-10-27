"""Typed settings document (PRD §3.3, reduced MVP set). Stored as one JSON row; validated on write."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GeneralSettings(BaseModel):
    launch_at_startup: bool = False
    start_minimized: bool = True
    keep_dot_visible: bool = True
    panel_autohide_seconds: int = Field(default=0, ge=0, le=600, description="0 = never")


class AppearanceSettings(BaseModel):
    dot_size: int = Field(default=44, ge=32, le=96)  # the pet; the UI offers 36 / 44 / 52
    dot_opacity: float = Field(default=0.95, ge=0.2, le=1.0)
    accent_color: str = Field(default="#8b5cf6", pattern=r"^#[0-9a-fA-F]{6}$")
    theme: Literal["dark"] = "dark"


class VoiceSettings(BaseModel):
    wake_word_enabled: bool = True
    wake_word_engine: Literal["livekit", "porcupine"] = "livekit"
    wake_word_threshold: float = Field(default=0.8, ge=0.1, le=0.99)  # tuned on real voice in Phase 0
    voice_replies_enabled: bool = True
    spoken_reminders_enabled: bool = False
    gemini_voice: str | None = None  # must be one the selected model exposes (PRD §3.3)
    mic_device: str | None = None
    double_click_activates_voice: bool = True
    call_me: str = Field(default="Boss", min_length=1, max_length=30)  # how Ziko addresses the user
    greet_on_wake: bool = True  # "Hey Ziko" → a short hello with today's plan before listening


class TaskSettings(BaseModel):
    default_priority: Literal["low", "medium", "high"] = "medium"
    default_reminder_offset_min: int = Field(default=15, ge=0, le=7 * 24 * 60)
    default_morning_hour: int = Field(default=9, ge=0, le=23, description="'tomorrow morning' → this hour")
    default_evening_hour: int = Field(default=20, ge=0, le=23, description="'tonight' → this hour")
    snooze_minutes: int = Field(default=10, ge=1, le=240)
    completed_retention_days: int = Field(default=30, ge=1, le=3650)
    timezone: str | None = None  # None → system local zone


class AISettings(BaseModel):
    model: str = "gemini-3.8-live"
    fallback_model: str = "gemini-2.5-flash-native-audio-preview-12-2025"
    interaction_timeout_s: int = Field(default=10, ge=5, le=120)  # mic auto-off after this much silence
    conversation_retention_days: int = Field(default=7, ge=0, le=365)
    show_audio_indicator: bool = True


class AppSettings(BaseModel):
    version: int = 3  # document format; see settings_service._upgrade
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    appearance: AppearanceSettings = Field(default_factory=AppearanceSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    tasks: TaskSettings = Field(default_factory=TaskSettings)
    ai: AISettings = Field(default_factory=AISettings)


class SettingsPatch(BaseModel):
    """Partial deep-merge payload; each group is optional and itself partial."""

    general: dict | None = None
    appearance: dict | None = None
    voice: dict | None = None
    tasks: dict | None = None
    ai: dict | None = None


class ApiKeyIn(BaseModel):
    api_key: str = Field(min_length=20, max_length=200)


class ApiKeyStatus(BaseModel):
    has_api_key: bool
    credential_store: Literal["keyring", "file", "none"]
