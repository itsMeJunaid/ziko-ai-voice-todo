"""Runtime configuration. Tauri injects ZIKO_PORT / ZIKO_TOKEN per launch; .env covers dev."""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "Ziko"


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ZIKO_", extra="ignore")

    host: str = "127.0.0.1"  # PRD §8.5: loopback only
    port: int = 8765
    token: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    data_dir: Path = Field(default_factory=default_data_dir)
    db_path: Path | None = None
    debug_content: bool = False  # log task titles only when explicitly enabled (PRD §11.4)
    log_level: str = "INFO"
    exit_on_stdin_eof: bool = False  # set by Tauri: parent death closes our stdin → exit (no orphans)
    # Tauri webview origins per platform + the Vite dev server. Requests from anywhere else are refused
    # by the browser; the bearer token is still required for every request regardless.
    cors_origins: list[str] = [
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "http://localhost:1420",
    ]

    @property
    def database_path(self) -> Path:
        return self.db_path or (self.data_dir / "ziko.db")

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
        _config.data_dir.mkdir(parents=True, exist_ok=True)
    return _config


def reset_config() -> None:  # tests
    global _config
    _config = None
