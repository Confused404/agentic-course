from datetime import datetime, timezone

from promo.cart import Cart, Line
from promo.coupons import Coupon

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


def cart(*lines):
    return Cart(tuple(Line(*x) for x in lines))


def pct(code, p, min_spend=0, **kw):
    return Coupon(code, "percent", percent=p, min_spend_cents=min_spend, **kw)


def bogo(code, sku, x, y, **kw):
    return Coupon(code, "bogo", buy_sku=sku, buy_qty=x, free_qty=y, **kw)


def fixed(code, cents, **kw):
    return Coupon(code, "fixed", amount_cents=cents, **kw)


def reasons(r):
    return [(x.code, x.reason) for x in r.rejected]


def applied(r):
    return [(a.code, a.discount_cents) for a in r.applied]
