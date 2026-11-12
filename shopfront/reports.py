"""Back-office reports used by the ops team (and by the nightly ops agent in Node 10).

Business rules:
- revenue_between(start, end): NET revenue in cents for orders whose placed_at falls on a UTC calendar
  day from `start` to `end` INCLUSIVE (dates as 'YYYY-MM-DD'). Net = order total minus that order's
  refunds with status 'issued' (whenever they were issued). Cancelled and returned orders are excluded
  entirely (a returned order was refunded in full outside the refunds table).
- low_stock(): active products whose stock is AT OR BELOW reorder_level, ordered by stock ascending,
  then id ascending.
"""
from __future__ import annotations

import sqlite3

from shopfront.db import rows


def revenue_between(conn: sqlite3.Connection, start: str, end: str) -> int:
    row = conn.execute(
        """SELECT COALESCE(SUM(o.total_cents - COALESCE(
                    (SELECT SUM(r.amount_cents) FROM refunds r WHERE r.order_id = o.id AND r.status = 'issued'), 0)), 0)
           FROM orders o
           WHERE date(o.placed_at) BETWEEN date(?) AND date(?)
             AND lower(trim(o.status)) NOT IN ('cancelled', 'returned')""",
        (start, end)).fetchone()
    return int(row[0])


def low_stock(conn: sqlite3.Connection) -> list[dict]:
    return rows(conn.execute(
        "SELECT id, sku, name, stock, reorder_level FROM products "
        "WHERE active = 1 AND stock <= reorder_level ORDER BY stock ASC, id ASC"))
