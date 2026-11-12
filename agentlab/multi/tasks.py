"""GIVEN: breadth-heavy analytics tasks over the shop database, with gold answers computed by SQL (Node 10).

Every task needs data about many products: a single agent has to pull all of it through its own context; a
multi-agent system can shard it. Gold answers come from the database, so grading is exact, not judged.
Definitions are spelled out in each question because "average rating" or "last 90 days" must mean the same thing
to the gold SQL, the tools and the model.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from shopfront import clock

MIN_REVIEWS = 16
WINDOW_DAYS = 90
RESTOCK_MIN_UNITS = 15


def since() -> str:
    return (clock.now() - timedelta(days=WINDOW_DAYS)).isoformat()


def _stats(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT p.id, p.sku, p.category, p.active, p.stock, p.reorder_level,
                  (SELECT COUNT(*) FROM reviews r WHERE r.product_id = p.id),
                  (SELECT AVG(rating) FROM reviews r WHERE r.product_id = p.id),
                  (SELECT COALESCE(SUM(oi.qty), 0) FROM order_items oi JOIN orders o ON o.id = oi.order_id
                    WHERE oi.product_id = p.id AND o.placed_at >= ? AND lower(trim(o.status)) != 'cancelled')
           FROM products p ORDER BY p.id""", (since(),)).fetchall()
    keys = ("id", "sku", "category", "active", "stock", "reorder_level", "reviews", "avg_rating", "units_90d")
    return [dict(zip(keys, r)) for r in rows]


def gold_lowest_rated_per_category(conn) -> dict[str, str]:
    best: dict[str, tuple[float, str]] = {}
    for s in _stats(conn):
        if s["reviews"] >= MIN_REVIEWS:
            key = (round(s["avg_rating"], 2), s["sku"])
            if s["category"] not in best or key < best[s["category"]]:
                best[s["category"]] = key
    return {c: v[1] for c, v in sorted(best.items())}


def gold_rated_below(conn, threshold: float = 3.6) -> list[str]:
    return sorted(s["sku"] for s in _stats(conn) if s["reviews"] >= MIN_REVIEWS
                  and round(s["avg_rating"], 2) < threshold)


def gold_top_units(conn, n: int = 3) -> list[str]:
    ranked = sorted(_stats(conn), key=lambda s: (-s["units_90d"], s["sku"]))
    return [s["sku"] for s in ranked[:n]]


def gold_restock(conn, min_units: int = RESTOCK_MIN_UNITS) -> list[str]:
    return sorted(s["sku"] for s in _stats(conn) if s["active"] and s["stock"] <= s["reorder_level"]
                  and s["units_90d"] >= min_units)


def gold_category_ratings(conn) -> dict[str, float]:
    rows = conn.execute("SELECT p.category, AVG(r.rating) FROM reviews r JOIN products p ON p.id = r.product_id "
                        "GROUP BY p.category ORDER BY p.category").fetchall()
    return {c: round(a, 2) for c, a in rows}


@dataclass(frozen=True)
class MultiTask:
    id: str
    question: str
    answer_kind: str                 # "list" (order matters), "set", "dict" (exact values), "dict_float" (±0.01)
    gold: Callable[[sqlite3.Connection], object]
    shard_hint: str = "category"     # how the work naturally splits


TASKS = [
    MultiTask("lowest_rated_per_category",
              f"For each product category, which product has the lowest average review rating? Only consider "
              f"products with at least {MIN_REVIEWS} reviews; average ratings rounded to 2 decimals; break ties by "
              f"SKU (alphabetical). Answer as an object mapping category -> SKU.", "dict",
              gold_lowest_rated_per_category),
    MultiTask("rated_below_3_6",
              f"List every product (by SKU) whose average review rating, rounded to 2 decimals, is below 3.60, "
              f"considering only products with at least {MIN_REVIEWS} reviews. Answer as a list of SKUs.", "set",
              gold_rated_below),
    MultiTask("top_units_90d",
              f"Which three products sold the most units in the last {WINDOW_DAYS} days (orders placed in that window, "
              f"excluding cancelled orders)? Ties "
              f"broken by SKU (alphabetical). Answer as a list of three SKUs, best first.", "list", gold_top_units),
    MultiTask("restock",
              f"Which ACTIVE products have stock at or below their reorder level AND sold at least "
              f"{RESTOCK_MIN_UNITS} units in the last {WINDOW_DAYS} days (orders placed in that window, excluding cancelled "
              f"orders)? Answer as a list of SKUs.",
              "set", gold_restock),
    MultiTask("category_ratings",
              "What is the average review rating of each category, across all its reviews, rounded to 2 decimals? "
              "Answer as an object mapping category -> number.", "dict_float", gold_category_ratings),
]


def grade(task: MultiTask, answer: object, conn: sqlite3.Connection) -> tuple[bool, str]:
    """Exact grading against the gold SQL. Returns (passed, detail)."""
    gold = task.gold(conn)
    if task.answer_kind == "list":
        ok = isinstance(answer, list) and [str(a).upper() for a in answer] == gold
    elif task.answer_kind == "set":
        ok = isinstance(answer, list) and {str(a).upper() for a in answer} == set(gold)
    elif task.answer_kind == "dict":
        ok = isinstance(answer, dict) and {str(k): str(v).upper() for k, v in answer.items()} == gold
    else:
        ok = (isinstance(answer, dict) and set(map(str, answer)) == set(gold)
              and all(isinstance(answer[k], (int, float)) and abs(float(answer[k]) - gold[k]) <= 0.01 for k in gold))
    return ok, "" if ok else f"wanted {gold}, got {answer}"
