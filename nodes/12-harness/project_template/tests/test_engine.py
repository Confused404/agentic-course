from promo.cart import Cart, Line
from promo.coupons import Coupon
from promo.engine import apply


def cart(*lines):
    return Cart(tuple(Line(*x) for x in lines))


def test_no_coupons():
    assert apply(cart(("A", 500, 2)), []).total_cents == 1000


def test_fixed_coupon():
    r = apply(cart(("A", 500, 2)), [Coupon("TEN", "fixed", amount_cents=1000 - 1)])
    assert r.total_cents == 1 and r.applied[0].discount_cents == 999


def test_total_never_negative():
    r = apply(cart(("A", 300, 1)), [Coupon("BIG", "fixed", amount_cents=500)])
    assert r.total_cents == 0 and r.applied[0].discount_cents == 300
