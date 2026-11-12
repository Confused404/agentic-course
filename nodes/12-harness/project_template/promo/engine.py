"""Applying coupons to a cart."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

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


def apply(cart: Cart, coupons: list[Coupon], now: datetime | None = None) -> Result:
    """Apply coupons in the order given. Today only "fixed" coupons are supported: each takes amount_cents off,
    and the total never goes below zero. Unknown kinds are rejected with reason "unsupported"."""
    total = cart.subtotal_cents
    result = Result(total)
    for c in coupons:
        if c.kind != "fixed":
            result.rejected.append(Rejected(c.code, "unsupported"))
            continue
        discount = min(c.amount_cents, total)
        total -= discount
        result.applied.append(Applied(c.code, discount))
    result.total_cents = total
    return result
