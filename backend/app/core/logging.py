"""Rotating file + console logging. Never log secrets; task content only with ZIKO_DEBUG_CONTENT=1."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from app.core.config import get_config

# The WebSocket token travels in the query string and uvicorn logs the request line on accept.
_SECRET = re.compile(r"(token=|Bearer\s+)[^&\s\"']+", re.IGNORECASE)


class RedactSecrets(logging.Filter):
    """Mask bearer/query tokens in every record before any handler writes it."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        clean = _SECRET.sub(r"\1***", msg)
        if clean != msg:
            record.msg, record.args = clean, None
        return True


def setup_logging() -> None:
    cfg = get_config()
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(cfg.log_level.upper())
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    redact = RedactSecrets()
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(redact)
    root.addHandler(console)
    log_dir = cfg.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(log_dir / "ziko.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(redact)
    root.addHandler(fh)


def redact_title(title: str) -> str:
    """Task titles are private; log a length marker unless content debugging is on."""
    return title if get_config().debug_content else f"<title:{len(title)} chars>"
