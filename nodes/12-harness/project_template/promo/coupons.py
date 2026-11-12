"""Coupon definitions. See BACKLOG.md for the kinds still to be implemented."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Coupon:
    code: str
    kind: str                       # "fixed" today; BACKLOG.md adds "percent" and "bogo"
    amount_cents: int = 0           # fixed
    percent: int = 0                # percent (1-100)
    min_spend_cents: int = 0        # percent
    buy_sku: str | None = None      # bogo
    buy_qty: int = 0                # bogo
    free_qty: int = 0               # bogo
    expires_at: str | None = None   # ISO 8601 (BACKLOG F4)
