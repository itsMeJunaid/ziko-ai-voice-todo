"""Alembic environment: metadata from app.models; URL from alembic config (set by app.database.migrate)."""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401  (registers tables)
from alembic import context
from app.database.base import Base

config = context.config
# CLI usage (`uv run alembic …`) → use the app's configured DB unless migrate.py already set a URL.
_url = config.get_main_option("sqlalchemy.url") or ""
if not _url or _url.endswith("ziko-dev.db"):
    from app.core.config import get_config

    config.set_main_option("sqlalchemy.url", get_config().database_url)
if config.config_file_name is not None and not config.get_main_option("skip_logging_config"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # render_as_batch: SQLite cannot ALTER constraints in place; batch mode recreates tables safely
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
