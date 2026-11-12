"""GIVEN tools and tasks: the tools must agree with the gold SQL, and scoping must hold."""
import json

import pytest

from agentlab.llm.types import ToolUseBlock
from agentlab.multi.tasks import TASKS, _stats, grade
from agentlab.multi.tools import MAX_STATS_IDS, analytics_tools, categories
from agentlab.tools.base import ToolRegistry


def run(reg, name, **args):
    r = reg.execute(ToolUseBlock("t1", name, args))
    return r.is_error, (r.text if r.is_error else json.loads(r.text))


def test_tools_agree_with_gold_stats(conn):
    reg = ToolRegistry(analytics_tools(conn))
    gold = {s["id"]: s for s in _stats(conn)}
    _, prods = run(reg, "list_products", category="kitchen")
    err, stats = run(reg, "product_stats", product_ids=[p["id"] for p in prods][:MAX_STATS_IDS])
    assert not err
    for s in stats:
        g = gold[s["id"]]
        assert s["reviews"] == g["reviews"] and s["units_90d"] == g["units_90d"]
        assert s["avg_rating"] == round(g["avg_rating"], 2)
        assert abs(s["rating_sum"] / s["reviews"] - g["avg_rating"]) < 1e-9, "rating_sum is exact"


def test_scope_is_enforced_and_named(conn):
    reg = ToolRegistry(analytics_tools(conn, ["bags"]))
    err, cats = run(reg, "list_categories")
    assert [c["category"] for c in cats] == ["bags"]
    err, msg = run(reg, "list_products", category="kitchen")
    assert err and "bags" in msg, "the error says what the worker CAN query"
    kitchen_id = conn.execute("SELECT id FROM products WHERE category = 'kitchen' LIMIT 1").fetchone()[0]
    assert run(reg, "product_stats", product_ids=[kitchen_id])[0]
    assert run(reg, "list_reviews", product_id=kitchen_id)[0]


def test_batch_limit(conn):
    reg = ToolRegistry(analytics_tools(conn))
    err, msg = run(reg, "product_stats", product_ids=list(range(1, MAX_STATS_IDS + 2)))
    assert err and "Split" in msg
    assert run(reg, "product_stats", product_ids=[])[0]


def test_reviews_are_marked_untrusted(conn):
    reg = ToolRegistry(analytics_tools(conn))
    err, out = run(reg, "list_reviews", product_id=1, limit=2)
    assert not err and "UNTRUSTED" in out["note"] and len(out["reviews"]) <= 2


def test_every_task_has_a_nontrivial_gold(conn):
    assert len(categories(conn)) == 6
    for t in TASKS:
        g = t.gold(conn)
        assert g, t.id
        ok, _ = grade(t, g if not isinstance(g, list) else list(g), conn)
        assert ok, f"{t.id}: gold must grade as correct"


@pytest.mark.parametrize("task_id,bad", [
    ("top_units_90d", "reversed"), ("rated_below_3_6", "drop_one"), ("category_ratings", "nudge"),
    ("lowest_rated_per_category", "drop_one")])
def test_grade_rejects_near_misses(conn, task_id, bad):
    t = next(t for t in TASKS if t.id == task_id)
    g = t.gold(conn)
    if bad == "reversed":
        ans = list(reversed(g))
    elif bad == "nudge":
        ans = {k: v + 0.02 for k, v in g.items()}
    elif isinstance(g, dict):
        ans = dict(list(g.items())[1:])
    else:
        ans = g[1:]
    assert not grade(t, ans, conn)[0]


def test_grade_tolerances(conn):
    t = next(t for t in TASKS if t.id == "category_ratings")
    g = t.gold(conn)
    assert grade(t, {k: v + 0.009 for k, v in g.items()}, conn)[0], "±0.01 on pooled averages"
    from agentlab.multi.tasks import _stats
    avg_of_avgs: dict = {}
    for s in _stats(conn):
        avg_of_avgs.setdefault(s["category"], []).append(s["avg_rating"])
    wrong = {c: sum(v) / len(v) for c, v in avg_of_avgs.items()}
    assert not grade(t, wrong, conn)[0], "an average of product averages must FAIL: that's the combination trap"
    s = next(t for t in TASKS if t.id == "rated_below_3_6")
    assert grade(s, [x.lower() for x in reversed(s.gold(conn))], conn)[0], "a set: order and case don't matter"


def test_tools_are_safe_from_parallel_workers(conn):
    """Workers share one connection. Without serialisation, sqlite3's statement cache returns short or empty
    results under threads, silently."""
    from concurrent.futures import ThreadPoolExecutor
    want = {s["id"]: s["units_90d"] for s in _stats(conn)}
    regs = [ToolRegistry(analytics_tools(conn, [c])) for c in categories(conn)]

    def work(reg):
        bad = 0
        for _ in range(15):
            err, cats = run(reg, "list_categories")
            err2, prods = run(reg, "list_products", category=cats[0]["category"])
            ids = [p["id"] for p in prods][:MAX_STATS_IDS]
            err3, stats = run(reg, "product_stats", product_ids=ids)
            bad += err or err2 or err3 or any(s["units_90d"] != want[s["id"]] for s in stats)
        return bad
    with ThreadPoolExecutor(6) as pool:
        assert sum(pool.map(work, regs)) == 0


def test_units_exclude_cancelled_orders(conn):
    from agentlab.multi.tasks import since
    pid = conn.execute("SELECT oi.product_id FROM order_items oi JOIN orders o ON o.id = oi.order_id "
                       "WHERE lower(trim(o.status)) = 'cancelled' AND o.placed_at >= ? LIMIT 1", (since(),)).fetchone()
    if pid is None:
        pytest.skip("no cancelled order in the window")
    total = conn.execute("SELECT SUM(oi.qty) FROM order_items oi JOIN orders o ON o.id = oi.order_id "
                         "WHERE oi.product_id = ? AND o.placed_at >= ?", (pid[0], since())).fetchone()[0]
    s = next(x for x in _stats(conn) if x["id"] == pid[0])
    assert s["units_90d"] < total
