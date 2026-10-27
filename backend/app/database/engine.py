"""SQLite engine + session factory. WAL mode and foreign keys on every connection."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_config

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        cfg = get_config()
        cfg.database_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(cfg.database_url, connect_args={"check_same_thread": False}, future=True)
        event.listen(_engine, "connect", _sqlite_pragmas)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, class_=Session)
    return _engine


def session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on any exception (PRD §10.3)."""
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine() -> None:  # tests / shutdown
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
