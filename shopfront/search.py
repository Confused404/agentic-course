"""Basic keyword product search (the 'before' picture for Node 07's retrieval work).

Business rules:
- ASCII case-insensitive substring match on product name OR description, as stored (no HTML decoding).
  Characters like % and _ in the query are literal (this is a substring match, not a LIKE pattern).
- An empty query matches every product. Only active products are returned.
- Results ordered by id. page is 1-based; page=1 returns the first `page_size` results; page < 1 is
  treated as 1.
"""
from __future__ import annotations

import sqlite3

from shopfront.db import rows


def search_products(conn: sqlite3.Connection, query: str, page: int = 1, page_size: int = 10) -> list[dict]:
    offset = page * page_size
    return rows(conn.execute(
        """SELECT id, sku, name, category, price_cents FROM products
           WHERE instr(name, ?) > 0 OR instr(description, ?) > 0
           ORDER BY id LIMIT ? OFFSET ?""",
        (query, query, page_size, offset)))
