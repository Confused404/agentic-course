from _helpers import NOW, applied, bogo, cart, reasons
from promo.engine import apply


def test_groups():
    r = apply(cart(("S", 300, 7), ("T", 100, 1)), [bogo("B", "S", 2, 1)], NOW)   # 7 // 3 = 2 groups -> 2 free
    assert applied(r) == [("B", 600)] and r.total_cents == 2100 + 100 - 600


def test_multiple_free_per_group():
    assert applied(apply(cart(("S", 100, 10)), [bogo("B", "S", 3, 2)], NOW)) == [("B", 400)]


def test_not_applicable_and_invalid():
    assert reasons(apply(cart(("S", 100, 2)), [bogo("B", "S", 2, 1)], NOW)) == [("B", "not_applicable")]
    assert reasons(apply(cart(("T", 100, 9)), [bogo("B", "S", 1, 1)], NOW)) == [("B", "not_applicable")]
    assert reasons(apply(cart(("S", 100, 9)), [bogo("B", "S", 0, 1)], NOW)) == [("B", "invalid")]
