"""The support assistant's tools, BOUND to one customer session (TEXTBOOK §5: identity comes from the
session, never from the model). No tool accepts a customer id."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from agentlab.config import ROOT
from agentlab.tools import Tool, ToolRegistry
from shopfront import services

HELP_CENTER = ROOT / "data" / "help_center"
_REASON = {"type": "string", "enum": list(services.REFUND_REASONS)}
_ORDER = {"type": "integer", "minimum": 1}


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def _front_matter(text: str) -> tuple[dict, str]:
    meta: dict[str, str] = {}
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        for line in fm.strip().splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
        return meta, body.strip()
    return meta, text


def search_help_center(query: str, k: int = 3, root: Path = HELP_CENTER) -> list[dict]:
    """Naive keyword search: score = number of distinct query words (>= 3 letters) found in the article.
    Node 07 replaces this with real retrieval and measures the difference."""
    words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) >= 3}
    hits = []
    for f in sorted(root.glob("*.md")):
        meta, body = _front_matter(f.read_text())
        text = body.lower()
        score = sum(1 for w in words if w in text)
        if score:
            hits.append((score, f.stem, {"slug": f.stem, "title": meta.get("title", f.stem),
                                         "status": meta.get("status", ""), "updated": meta.get("updated", ""),
                                         "excerpt": body[:700]}))
    hits.sort(key=lambda h: (-h[0], h[1]))
    return [h[2] for h in hits[:k]]


def make_support_tools(conn: sqlite3.Connection, customer_id: int, actor: str = "agent:support") -> ToolRegistry:
    # why closures: customer_id and actor are captured here, so the model can't choose them
    def get_my_orders(limit: int = 10):
        return services.list_orders_for_customer(conn, customer_id, limit)

    def lookup_order(order_id: int):
        return services.get_order(conn, order_id, customer_id=customer_id)

    def check_refund_eligibility(order_id: int, reason: str):
        return services.refund_eligibility(conn, order_id, reason, customer_id=customer_id)

    def issue_refund(order_id: int, amount_cents: int, reason: str):
        return services.issue_refund(conn, order_id, amount_cents, reason, actor=actor, customer_id=customer_id)

    def cancel_order(order_id: int):
        return services.cancel_order(conn, order_id, actor, customer_id=customer_id)

    def escalate_to_human(summary: str, order_id: int | None = None):
        return services.escalate_to_human(conn, customer_id, summary, order_id, actor)

    def search(query: str):
        return search_help_center(query)

    return ToolRegistry([
        Tool("get_my_orders", "List this customer's most recent orders (id, status, dates, total in cents). "
             "Use when the customer doesn't give an order number.",
             _obj({"limit": {"type": "integer", "minimum": 1, "maximum": 20}}, []), get_my_orders),
        Tool("lookup_order", "Get one of this customer's orders: status, placed/shipped/delivered dates, items, "
             "total in cents, existing refunds. Returns NOT_FOUND for orders that aren't theirs.",
             _obj({"order_id": _ORDER}, ["order_id"]), lookup_order),
        Tool("check_refund_eligibility", "Check whether an order can be refunded for a given reason, applying the "
             "official policy (windows, tiers, damaged items). No side effects. Returns eligible, problems, "
             "window_days and max_refundable_cents.",
             _obj({"order_id": _ORDER, "reason": _REASON}, ["order_id", "reason"]), check_refund_eligibility),
        Tool("issue_refund", "Issue a refund to the original payment method. Check eligibility first. Refunds over "
             "$200 are queued for human approval. Returns the refund status.",
             _obj({"order_id": _ORDER, "amount_cents": {"type": "integer", "minimum": 1}, "reason": _REASON},
                  ["order_id", "amount_cents", "reason"]), issue_refund, side_effects=True),
        Tool("cancel_order", "Cancel an order that has not shipped yet (status 'placed'). Shipped orders cannot be "
             "cancelled.", _obj({"order_id": _ORDER}, ["order_id"]), cancel_order, side_effects=True),
        Tool("escalate_to_human", "Hand the case to a human agent with a summary. Use for lost packages, warranty "
             "claims, safety issues, or anything your tools can't resolve. Returns a ticket id.",
             _obj({"summary": {"type": "string", "minLength": 10}, "order_id": _ORDER}, ["summary"]),
             escalate_to_human, side_effects=True),
        Tool("search_help_center", "Search Shopfront's help-center articles (policies, shipping, care guides). "
             "Returns up to 3 articles with title, status (current/archived), last-updated date and an excerpt.",
             _obj({"query": {"type": "string", "minLength": 2}}, ["query"]), search),
    ])
