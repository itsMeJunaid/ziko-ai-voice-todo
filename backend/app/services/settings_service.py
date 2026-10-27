"""Settings document persistence + API-key storage in the OS credential store (PRD §11.1)."""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.config import get_config
from app.core.errors import Validation
from app.models.settings import AppSettingsRow
from app.schemas.settings import AppSettings, SettingsPatch

log = logging.getLogger(__name__)

KEYRING_SERVICE = "ziko-desktop"
KEYRING_USER = "gemini_api_key"


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in patch.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _upgrade(data: dict[str, Any]) -> dict[str, Any]:
    """One-off fixes for documents saved by older builds. v2: wake threshold default 0.5 → 0.8."""
    if data.get("version", 1) < 2:
        voice = data.get("voice") or {}
        if voice.get("wake_word_threshold") == 0.5:
            voice["wake_word_threshold"] = 0.8
        data["version"] = 2
    if data["version"] < 3:  # v3: mic off after 10 s (was 20), small pet dot (was the 56 px orb)
        ai, look = data.get("ai") or {}, data.get("appearance") or {}
        if ai.get("interaction_timeout_s") == 20:
            ai["interaction_timeout_s"] = 10
        if look.get("dot_size") == 56:
            look["dot_size"] = 44
        data["version"] = 3
    return data


class SettingsService:
    def __init__(self, session: Session, clock: Clock) -> None:
        self.session = session
        self.clock = clock

    def get(self) -> AppSettings:
        row = self.session.get(AppSettingsRow, 1)
        if row is None:
            return AppSettings()
        try:
            return AppSettings.model_validate(_upgrade(json.loads(row.data)))
        except Exception as e:  # corrupted row → actionable error, keep defaults (PRD §10.3)
            log.error("settings row invalid, using defaults: %s", e)
            return AppSettings()

    def replace(self, settings: AppSettings) -> AppSettings:
        row = self.session.get(AppSettingsRow, 1)
        now = self.clock.now_utc()
        payload = settings.model_dump_json()
        if row is None:
            self.session.add(AppSettingsRow(id=1, data=payload, updated_at=now))
        else:
            row.data, row.updated_at = payload, now
        self.session.flush()
        return settings

    def patch(self, patch: SettingsPatch) -> AppSettings:
        current = self.get().model_dump()
        merged = _deep_merge(current, {k: v for k, v in patch.model_dump().items() if v is not None})
        try:
            return self.replace(AppSettings.model_validate(merged))
        except ValueError as e:
            raise Validation("Invalid settings", details=str(e)) from e

    def reset(self) -> AppSettings:
        return self.replace(AppSettings())


# ---------------------------------------------------------------- API key (never returned to clients)


class CredentialStore:
    """keyring (Windows Credential Manager / macOS Keychain / Secret Service) with a 0600-file fallback."""

    def __init__(self) -> None:
        self._fallback = get_config().data_dir / "credentials.json"
        self.backend: Literal["keyring", "file", "none"] = "none"
        try:
            import keyring
            from keyring.backends.fail import Keyring as FailKeyring

            kr = keyring.get_keyring()
            self.backend = "file" if isinstance(kr, FailKeyring) else "keyring"
        except Exception:
            self.backend = "file"

    def get_api_key(self) -> str | None:
        if self.backend == "keyring":
            try:
                import keyring

                return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
            except Exception as e:
                log.warning("keyring read failed (%s); falling back to file", type(e).__name__)
                self.backend = "file"
        return self._read_file().get(KEYRING_USER)

    def set_api_key(self, value: str) -> None:
        if self.backend == "keyring":
            try:
                import keyring

                keyring.set_password(KEYRING_SERVICE, KEYRING_USER, value)
                return
            except Exception as e:
                log.warning("keyring write failed (%s); falling back to file", type(e).__name__)
                self.backend = "file"
        data = self._read_file()
        data[KEYRING_USER] = value
        self._write_file(data)

    def delete_api_key(self) -> None:
        if self.backend == "keyring":
            try:
                import keyring

                keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
            except Exception:
                pass
        data = self._read_file()
        if data.pop(KEYRING_USER, None) is not None or not data:
            self._write_file(data)

    def has_api_key(self) -> bool:
        return bool(self.get_api_key())

    def _read_file(self) -> dict[str, str]:
        try:
            return json.loads(self._fallback.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except Exception:
            return {}

    def _write_file(self, data: dict[str, str]) -> None:
        p: Path = self._fallback
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")
        if os.name != "nt":
            p.chmod(stat.S_IRUSR | stat.S_IWUSR)
