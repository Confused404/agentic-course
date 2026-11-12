"""Applying coupons to a cart (reference implementation of BACKLOG F1-F4)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from promo.cart import Cart
from promo.coupons import Coupon


@dataclass(frozen=True)
class Applied:
    code: str
    discount_cents: int


@dataclass(frozen=True)
class Rejected:
    code: str
    reason: str


@dataclass
class Result:
    total_cents: int
    applied: list[Applied] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)


def _expiry(c: Coupon) -> datetime | None | str:
    if c.expires_at is None:
        return None
    try:
        t = datetime.fromisoformat(c.expires_at)
    except ValueError:
        return "invalid"
    return "invalid" if t.tzinfo is None else t


def apply(cart: Cart, coupons: list[Coupon], now: datetime | None = None) -> Result:
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    rejected: dict[int, str] = {}
    seen: set[str] = set()
    for i, c in enumerate(coupons):
        key = c.code.casefold()
        if key in seen:
            rejected[i] = "duplicate"
            continue
        seen.add(key)
        exp = _expiry(c)
        if exp == "invalid":
            rejected[i] = "invalid"
        elif exp is not None and not now < exp:
            rejected[i] = "expired"
        elif c.kind not in ("fixed", "percent", "bogo"):
            rejected[i] = "unsupported"
    live = [(i, c) for i, c in enumerate(coupons) if i not in rejected]
    subtotal = cart.subtotal_cents
    total = subtotal
    applied: list[Applied] = []

    for i, c in live:
        if c.kind != "bogo":
            continue
        if c.buy_qty < 1 or c.free_qty < 1:
            rejected[i] = "invalid"
            continue
        unit = cart.unit_of(c.buy_sku) if c.buy_sku else None
        groups = cart.qty_of(c.buy_sku) // (c.buy_qty + c.free_qty) if unit is not None else 0
        if not groups:
            rejected[i] = "not_applicable"
            continue
        d = min(groups * c.free_qty * unit, total)
        total -= d
        applied.append(Applied(c.code, d))

    best: tuple[int, int] | None = None     # (discount, index)
    candidates = []
    for i, c in live:
        if c.kind != "percent":
            continue
        if not 1 <= c.percent <= 100:
            rejected[i] = "invalid"
        elif subtotal < c.min_spend_cents:
            rejected[i] = "min_spend"
        else:
            d = total * c.percent // 100
            candidates.append((i, d))
            if best is None or d > best[0]:
                best = (d, i)
    for i, d in candidates:
        if best and i == best[1]:
            total -= d
            applied.append(Applied(coupons[i].code, d))
        else:
            rejected[i] = "stacking"

    for i, c in live:
        if c.kind == "fixed":
            d = min(c.amount_cents, total)
            total -= d
            applied.append(Applied(c.code, d))
    return Result(total, applied, [Rejected(coupons[i].code, rejected[i]) for i in sorted(rejected)])
