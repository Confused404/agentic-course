from _helpers import NOW, applied, bogo, cart, fixed, pct, reasons
from promo.engine import apply


def test_order_of_application_regardless_of_input_order():
    c = cart(("S", 1000, 3))                                     # subtotal 3000
    r = apply(c, [fixed("F", 100), pct("P", 10), bogo("B", "S", 2, 1)], NOW)
    # bogo 1000 -> 2000; percent 10% of 2000 = 200 -> 1800; fixed 100 -> 1700
    assert applied(r) == [("B", 1000), ("P", 200), ("F", 100)] and r.total_cents == 1700


def test_best_percent_wins():
    r = apply(cart(("A", 1000, 1)), [pct("SMALL", 5), pct("BIG", 20), pct("BIG2", 20)], NOW)
    assert applied(r) == [("BIG", 200)]
    assert reasons(r) == [("SMALL", "stacking"), ("BIG2", "stacking")]


def test_min_spend_uses_subtotal_not_discounted():
    r = apply(cart(("S", 1000, 3)), [bogo("B", "S", 2, 1), pct("P", 10, 3000)], NOW)
    assert applied(r) == [("B", 1000), ("P", 200)]


def test_duplicates_case_insensitive_and_first():
    r = apply(cart(("A", 1000, 1)), [fixed("save", 100), fixed("SAVE", 300), pct("p", 50), pct("P", 10)], NOW)
    assert reasons(r) == [("SAVE", "duplicate"), ("P", "duplicate")]
    assert applied(r) == [("p", 500), ("save", 100)]


def test_floor_at_zero_records_actual_discount():
    r = apply(cart(("A", 500, 1)), [fixed("X", 400), fixed("Y", 400)], NOW)
    assert applied(r) == [("X", 400), ("Y", 100)] and r.total_cents == 0


def test_rejected_in_input_order_whatever_the_reason():
    c = cart(("A", 1000, 1))
    r = apply(c, [pct("BAD", 0), fixed("OLD", 1, expires_at="2020-01-01T00:00:00+00:00"), pct("A", 10),
                  pct("B", 5)], NOW)
    assert reasons(r) == [("BAD", "invalid"), ("OLD", "expired"), ("B", "stacking")]
