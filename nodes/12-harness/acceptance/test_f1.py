from _helpers import NOW, applied, cart, pct, reasons
from promo.engine import apply


def test_percent_basic_and_floor():
    r = apply(cart(("A", 999, 1)), [pct("P10", 10)], NOW)          # 99.9 -> 99
    assert applied(r) == [("P10", 99)] and r.total_cents == 900


def test_min_spend_boundary():
    assert applied(apply(cart(("A", 5000, 1)), [pct("P", 20, 5000)], NOW)) == [("P", 1000)]
    r = apply(cart(("A", 4999, 1)), [pct("P", 20, 5000)], NOW)
    assert reasons(r) == [("P", "min_spend")] and r.total_cents == 4999


def test_invalid_percent():
    for p in (0, 101, -5):
        assert reasons(apply(cart(("A", 100, 1)), [pct("P", p)], NOW)) == [("P", "invalid")]
    assert applied(apply(cart(("A", 100, 1)), [pct("P", 100)], NOW)) == [("P", 100)]
