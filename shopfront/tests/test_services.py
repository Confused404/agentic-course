"""Shopfront's own tests. These must pass on `main` from day one (`make check`).

They also document the fixtures' expected behaviour, which every eval in the course relies on.
"""
import hashlib
import json

import pytest

from shopfront import db, services
from shopfront.seed import build


@pytest.fixture()
def conn(tmp_path):
    path = tmp_path / "shop.db"
    build(path, out_dir=tmp_path)
    c = db.connect(path)
    yield c
    c.close()


def test_seed_is_deterministic(tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    build(a, out_dir=tmp_path)
    build(b, out_dir=tmp_path)
    assert hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()


def test_status_is_normalized(conn):
    assert services.get_order(conn, 4821)["status"] == "delivered"   # raw: 'Delivered'
    assert services.get_order(conn, 4826)["status"] == "delivered"   # raw: 'DELIVERED '


def test_order_4821_outside_standard_window_but_inside_damaged(conn):
    assert not services.refund_eligibility(conn, 4821, "changed_mind")["eligible"]
    assert services.refund_eligibility(conn, 4821, "damaged")["eligible"]


def test_plus_tier_window(conn):
    assert services.refund_eligibility(conn, 4823, "changed_mind")["eligible"]       # 40d, plus
    assert not services.refund_eligibility(conn, 4830, "changed_mind")["eligible"]   # 50d, plus


def test_undelivered_and_cancelled_not_refundable(conn):
    assert not services.refund_eligibility(conn, 4824, "other")["eligible"]
    assert not services.refund_eligibility(conn, 4827, "other")["eligible"]


def test_one_refund_per_order(conn):
    v = services.refund_eligibility(conn, 4828, "changed_mind")
    assert not v["eligible"] and "already" in " ".join(v["problems"])


def test_large_refund_needs_approval(conn):
    r = services.issue_refund(conn, 4826, 34999, "changed_mind", actor="test")
    assert r["status"] == "pending_approval"


def test_policy_violation_raises_and_is_audited(conn):
    with pytest.raises(services.ShopError) as e:
        services.issue_refund(conn, 4821, 8000, "changed_mind", actor="test")
    assert e.value.code == "POLICY"
    logged = conn.execute("SELECT action FROM audit_log").fetchall()
    assert [r[0] for r in logged] == ["refund_denied"]


def test_case_duplicate_customers(conn):
    assert [c["id"] for c in services.find_customers_by_email(conn, "JANE.OKAFOR@example.com")] == [9004, 9005]


def test_side_files_written(tmp_path):
    build(tmp_path / "x.db", out_dir=tmp_path)
    assert (tmp_path / "help_center" / "refund-policy.md").exists()
    assert (tmp_path / "help_center" / "returns-policy-2025.md").exists()
    adv = json.loads((tmp_path / "adversarial_index.json").read_text())
    assert sum(a["is_attack"] for a in adv) >= 10 and sum(not a["is_attack"] for a in adv) >= 6


def test_window_boundaries_are_inclusive(conn):
    assert services.refund_eligibility(conn, 4831, "changed_mind")["eligible"]        # day 30, standard
    assert not services.refund_eligibility(conn, 4832, "changed_mind")["eligible"]    # day 31
    assert services.refund_eligibility(conn, 4833, "changed_mind")["eligible"]        # day 45, plus
    assert not services.refund_eligibility(conn, 4834, "changed_mind")["eligible"]    # day 46


def test_swollen_power_bank_past_damaged_window(conn):
    assert not services.refund_eligibility(conn, 4835, "damaged")["eligible"]         # 90 days


def test_ownership_is_enforced_and_indistinguishable(conn):
    with pytest.raises(services.ShopError) as mine:
        services.get_order(conn, 4829, customer_id=9004)        # belongs to the OTHER Jane (9005)
    with pytest.raises(services.ShopError) as missing:
        services.get_order(conn, 99999, customer_id=9004)
    assert mine.value.code == missing.value.code == "NOT_FOUND"
    assert services.get_order(conn, 4829, customer_id=9005)["id"] == 4829


def test_db_enforces_one_live_refund_even_if_checks_are_bypassed(conn):
    import sqlite3
    conn.execute("INSERT INTO refunds (order_id, amount_cents, reason, status, actor, created_at) "
                 "VALUES (4822, 100, 'other', 'issued', 't', 'x')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO refunds (order_id, amount_cents, reason, status, actor, created_at) "
                     "VALUES (4822, 100, 'other', 'issued', 't', 'x')")


def test_cancel_only_placed(conn):
    assert services.cancel_order(conn, 4825, actor="t")["status"] == "cancelled"
    with pytest.raises(services.ShopError):
        services.cancel_order(conn, 4824, actor="t")


def test_lost_package_has_transit_days(conn):
    assert services.get_order(conn, 4824)["business_days_in_transit"] > 10


def test_fixture_totals_match_items(conn):
    for oid in range(4821, 4837):
        o = services.get_order(conn, oid)
        assert o["total_cents"] == sum(i["qty"] * i["unit_price_cents"] for i in o["items"]), oid


def test_no_background_delivery_in_the_future(conn):
    assert conn.execute("SELECT count(*) FROM orders WHERE delivered_at > '2026-11-01T12:00:00+00:00'").fetchone()[0] == 0


def test_bool_amount_rejected(conn):
    with pytest.raises(services.ShopError):
        services.issue_refund(conn, 4822, True, "changed_mind", actor="t")
