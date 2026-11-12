"""Acceptance tests for Shopfront's seeded bugs. These FAIL on main on purpose: `shopdev` (your coding agent from this
node) fixes the code in shopfront/pricing.py, reports.py and search.py until they pass. shopdev may run these tests
but may not edit them (its permission gate denies it). The rules are in each module's docstring."""
import pytest

from shopfront import db
from shopfront.pricing import cart_total
from shopfront.reports import low_stock, revenue_between
from shopfront.search import search_products


# ---------------------------------------------------------------- pricing
@pytest.mark.parametrize("items,codes,tier,expected", [
    ([(2995, 1)], ["SAVE10"], "standard", 2696),                 # 2695.5 rounds half-up
    ([(1005, 1)], ["SAVE10"], "standard", 905),                  # 904.5 -> 905
    ([(10000, 1)], ["SAVE10", "SAVE20"], "standard", 8000),      # only the best percentage applies
    ([(10000, 1)], ["PLUS15"], "standard", 10000),               # plus-only code ignored for standard
    ([(10000, 1)], ["PLUS15", "SAVE10"], "plus", 8500),
    ([(10000, 1)], ["SAVE20", "PLUS15"], "plus", 8000),
    ([(2400, 1)], ["FLAT5"], "standard", 2400),                  # FLAT5 needs > $25
    ([(2500, 1)], ["FLAT5"], "standard", 2500),                  # strictly greater
    ([(2600, 1)], ["FLAT5"], "standard", 2100),
    ([(3000, 1)], ["SAVE20", "FLAT5"], "standard", 2400),        # 2400 after percent: no FLAT5
    ([(5000, 2)], ["FLAT5", "flat5"], "standard", 9500),         # duplicates count once, case-insensitive
    ([(5000, 2)], ["save10"], "standard", 9000),
    ([(5000, 2)], ["BOGUS"], "standard", 10000),
])
def test_pricing_rules(items, codes, tier, expected):
    assert cart_total(items, codes, tier) == expected


# ---------------------------------------------------------------- reports
@pytest.fixture()
def rconn(tmp_path):
    c = db.connect(tmp_path / "r.db")
    db.init_schema(c)
    c.execute("INSERT INTO customers VALUES (1, 'a@x', 'A', 'standard', '2025-01-01T00:00:00+00:00')")
    orders = [  # id, status, placed_at, total
        (1, "delivered", "2026-10-01T00:00:00+00:00", 1000),
        (2, "Delivered", "2026-10-02T23:59:00+00:00", 2000),   # last day, late evening: inside
        (3, "delivered", "2026-10-03T00:00:00+00:00", 4000),   # outside
        (4, " Cancelled", "2026-10-01T10:00:00+00:00", 8000),  # excluded (messy casing)
        (5, "returned", "2026-10-02T10:00:00+00:00", 16000),   # excluded
        (6, "shipped", "2026-10-02T11:00:00+00:00", 500),
        (7, " Returned ", "2026-10-01T09:00:00+00:00", 32000),  # excluded (messy casing)
        (8, "delivered", "2026-10-02T22:00:00-05:00", 64000),  # = 2026-10-03 03:00 UTC: outside
        (9, "delivered", "2026-10-01T12:00:00+00:00", 3000),   # two issued refunds: subtract both, count once
    ]
    c.executemany("INSERT INTO orders (id, customer_id, status, placed_at, total_cents, shipping_address) "
                  "VALUES (?, 1, ?, ?, ?, 'x')", orders)
    c.executemany("INSERT INTO refunds (order_id, amount_cents, reason, status, actor, created_at) VALUES (?,?,?,?,?,?)",
                  [(1, 300, "other", "issued", "t", "2026-10-20T00:00:00+00:00"),       # subtracted (date irrelevant)
                   (2, 700, "other", "pending_approval", "t", "2026-10-05T00:00:00+00:00"),  # not subtracted
                   (9, 100, "other", "issued", "t", "2026-10-05T00:00:00+00:00"),
                   (9, 200, "other", "denied", "t", "2026-10-06T00:00:00+00:00")])
    c.execute("DROP INDEX one_live_refund_per_order")   # historical data predates the invariant
    c.execute("INSERT INTO refunds (order_id, amount_cents, reason, status, actor, created_at) "
              "VALUES (9, 400, 'other', 'issued', 't', '2026-10-07T00:00:00+00:00')")
    c.executemany("INSERT INTO products (id, sku, name, category, description, price_cents, stock, reorder_level, active) "
                  "VALUES (?, ?, ?, 'k', 'd', 100, ?, 5, ?)",
                  [(5, "E", "e", 4, 1), (1, "A", "a", 5, 1), (2, "B", "b", 4, 1), (3, "C", "c", 6, 1), (4, "D", "d", 0, 0)])
    c.commit()
    yield c
    c.close()


def test_revenue_is_net_inclusive_and_excludes_cancelled_and_returned(rconn):
    assert revenue_between(rconn, "2026-10-01", "2026-10-02") == (1000 - 300) + 2000 + 500 + (3000 - 100 - 400)
    assert revenue_between(rconn, "2026-10-03", "2026-10-03") == 4000 + 64000


def test_low_stock_at_or_below_ordered(rconn):
    assert [p["id"] for p in low_stock(rconn)] == [2, 5, 1]


# ---------------------------------------------------------------- search
@pytest.fixture()
def sconn(tmp_path):
    c = db.connect(tmp_path / "s.db")
    db.init_schema(c)
    prods = [(i, f"S{i}", f"Trailhead Tent {i}" if i % 2 else f"Lamp {i}", "x", "desc", 100, 1, 5, 0 if i == 3 else 1)
             for i in range(1, 26)]
    prods += [(26, "S26", "Mug 100% ceramic", "x", "desc", 100, 1, 5, 1), (27, "S27", "Mug_large", "x", "desc", 100, 1, 5, 1)]
    c.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?)", prods)
    c.commit()
    yield c
    c.close()


def test_search_first_page_case_insensitive_active_only(sconn):
    ids = [p["id"] for p in search_products(sconn, "TENT", page=1, page_size=5)]
    assert ids == [1, 5, 7, 9, 11], "page 1 starts at the first match; 3 is inactive"
    assert [p["id"] for p in search_products(sconn, "tent", page=2, page_size=5)] == [13, 15, 17, 19, 21]


def test_search_edge_cases(sconn):
    assert [p["id"] for p in search_products(sconn, "", page=1, page_size=3)] == [1, 2, 4]
    assert [p["id"] for p in search_products(sconn, "lamp", page=0, page_size=2)] == [2, 4]
    assert [p["id"] for p in search_products(sconn, "_")] == [27], "_ is a literal, not a LIKE wildcard"
    assert [p["id"] for p in search_products(sconn, "100%")] == [26]
