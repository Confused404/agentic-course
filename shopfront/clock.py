"""A controllable clock.

Shopfront never calls datetime.now() directly. "Today" is 2026-11-01T12:00:00Z unless
SHOPFRONT_NOW is set. Why: refund eligibility depends on the date, and an eval that passes
today and fails next month is not an eval, it is a time bomb (Node 04 §2, "environment noise").
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

DEFAULT_NOW = "2026-11-01T12:00:00+00:00"


def now() -> datetime:
    return datetime.fromisoformat(os.environ.get("SHOPFRONT_NOW", DEFAULT_NOW))


def now_iso() -> str:
    return now().isoformat()


def parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
