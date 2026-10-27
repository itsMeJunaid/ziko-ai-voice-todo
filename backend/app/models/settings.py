from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, UTCDateTime


class AppSettingsRow(Base):
    """Single-row table holding the typed settings document as JSON (schema in schemas/settings.py)."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    data: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
