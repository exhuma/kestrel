"""Shared naive-UTC clock normalization for the board persistence stores.

SQLite's ``DateTime`` column round-trips naive datetimes; normalizing
every clock read through one place keeps stored and injected-for-tests
values comparable without a tz-aware/naive mismatch.
"""
from __future__ import annotations

from datetime import datetime, timezone


def now_utc(value: datetime | None) -> datetime:
    """Return *value* (or the current time) as naive UTC."""
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
