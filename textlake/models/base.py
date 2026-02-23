"""Declarative base for textlake tables; separate from MeritMolt and
MeritMolt schema.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class TextLakeBase(DeclarativeBase):
    """Declarative base for textlake tables (mb_*, crawl_*, raw_capture)."""

    pass
