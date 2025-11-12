from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from dateutil import tz

def _get_tz() -> tz.tzfile:
    name = os.environ.get("SCRAPER_TZ", "Asia/Karachi")
    return tz.gettz(name) or tz.UTC

def normalize_datetime(value: str, date_only: bool = False) -> str:
    """
    Normalize incoming date/time string to ISO formats in local timezone.
    - If `date_only` is True, returns YYYY-MM-DD.
    - Otherwise returns 'YYYY-MM-DD HH:MM'.
    """
    value = (value or "").strip()
    if not value:
        return value

    # Try a few formats quickly
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%d %b %Y %H:%M",
        "%d %b %Y",
    ]
    dt: Optional[datetime] = None
    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            # naive datetimes are assumed UTC, convert to local
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz.UTC)
            break
        except Exception:
            continue

    if dt is None:
        # last-ditch: try fromisoformat
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz.UTC)
        except Exception:
            return value  # return as-is if unknown

    local_dt = dt.astimezone(_get_tz())
    if date_only:
        return local_dt.strftime("%Y-%m-%d")
    return local_dt.strftime("%Y-%m-%d %H:%M")