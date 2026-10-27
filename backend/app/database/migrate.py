"""Run Alembic programmatically at startup so the packaged sidecar needs no CLI."""

from __future__ import annotations

import logging
from pathlib import Path

from alembic.config import Config as AlembicConfig

from alembic import command
from app.core.config import get_config

log = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[2]


def alembic_config(db_url: str | None = None) -> AlembicConfig:
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url or get_config().database_url)
    return cfg


def upgrade_to_head(db_url: str | None = None) -> None:
    command.upgrade(alembic_config(db_url), "head")
    log.info("database schema at head")
