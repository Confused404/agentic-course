"""python -m promo explain CART.json"""
from __future__ import annotations

import json
import sys
from datetime import datetime

from promo.cart import Cart, Line
from promo.coupons import Coupon
from promo.engine import apply


def _dollars(cents: int) -> str:
    return f"${cents // 100}.{cents % 100:02d}"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] != "explain":
        print("error: usage: python -m promo explain CART.json", file=sys.stderr)
        return 2
    try:
        with open(args[1]) as f:
            data = json.load(f)
        cart = Cart(tuple(Line(str(x["sku"]), int(x["unit_cents"]), int(x["qty"])) for x in data["lines"]))
        coupons = [Coupon(**c) for c in data.get("coupons", [])]
        now = datetime.fromisoformat(data["now"]) if data.get("now") else None
        r = apply(cart, coupons, now)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for a in r.applied:
        print(f"APPLIED {a.code} -{_dollars(a.discount_cents)}")
    for x in r.rejected:
        print(f"REJECTED {x.code} ({x.reason})")
    print(f"TOTAL {_dollars(r.total_cents)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
