"""Discount codes and cart totals.

Business rules (source of truth; the tests in nodes/03-*/tests encode these):
- Codes are case-insensitive. Unknown codes are ignored. A code given twice counts once.
- SAVE10 = 10% off, SAVE20 = 20% off, PLUS15 = 15% off (plus-tier only; ignored for others).
- At most ONE percentage code applies per cart: if several are given, the largest valid one wins.
- The percentage applies to the subtotal; the RESULTING price is rounded half-up to the nearest cent
  (e.g. 2995 at 10% off = 2695.5 -> 2696).
- FLAT5 = 500 cents off, applied after the percentage, only if that discounted total is over 2500 cents
  (strictly greater). Totals never go below 0.
"""
from __future__ import annotations

PERCENT_CODES = {"SAVE10": 10, "SAVE20": 20, "PLUS15": 15}
FLAT_CODES = {"FLAT5": 500}
FLAT_MIN_CENTS = 2500


def apply_percent(price_cents: int, percent: int) -> int:
    # integer arithmetic, round half up: floor((x * (100 - p) + 50) / 100)
    return (price_cents * (100 - percent) + 50) // 100


def cart_total(items: list[tuple[int, int]], codes: list[str], tier: str = "standard") -> int:
    """items: [(unit_price_cents, qty), ...]. Returns the total in cents after discounts."""
    subtotal = sum(price * qty for price, qty in items)
    unique = {c.upper() for c in codes}
    percents = [PERCENT_CODES[c] for c in unique if c in PERCENT_CODES and (c != "PLUS15" or tier == "plus")]
    total = apply_percent(subtotal, max(percents)) if percents else subtotal
    for code in sorted(unique & FLAT_CODES.keys()):
        if total > FLAT_MIN_CENTS:
            total -= FLAT_CODES[code]
    return max(total, 0)
