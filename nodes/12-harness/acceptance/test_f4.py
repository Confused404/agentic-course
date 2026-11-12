from datetime import datetime

import pytest
from _helpers import NOW, applied, cart, fixed, pct, reasons
from promo.engine import apply


def test_expiry_boundary_and_offsets():
    c = cart(("A", 1000, 1))
    assert reasons(apply(c, [fixed("X", 100, expires_at="2026-11-04T12:00:00+00:00")], NOW)) == [("X", "expired")]
    assert applied(apply(c, [fixed("X", 100, expires_at="2026-11-04T07:00:01-05:00")], NOW)) == [("X", 100)]
    assert reasons(apply(c, [fixed("X", 100, expires_at="2026-11-04T06:59:59-05:00")], NOW)) == [("X", "expired")]


def test_naive_expiry_is_invalid_and_none_never_expires():
    c = cart(("A", 1000, 1))
    assert reasons(apply(c, [fixed("X", 100, expires_at="2030-01-01T00:00:00")], NOW)) == [("X", "invalid")]
    assert applied(apply(c, [fixed("X", 100, expires_at=None)], NOW)) == [("X", 100)]


def test_naive_now_raises_and_default_now_works():
    with pytest.raises(ValueError):
        apply(cart(("A", 1000, 1)), [], datetime(2026, 1, 1))
    assert apply(cart(("A", 1000, 1)), [fixed("X", 1, expires_at="2999-01-01T00:00:00+00:00")]).total_cents == 999


def test_expired_percent_does_not_compete():
    r = apply(cart(("A", 1000, 1)), [pct("OLD", 50, expires_at="2020-01-01T00:00:00+00:00"), pct("NEW", 10)], NOW)
    assert applied(r) == [("NEW", 100)] and reasons(r) == [("OLD", "expired")]
