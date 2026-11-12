"""The support assistant's tools, BOUND to one customer session (TEXTBOOK §5: identity comes from the
session, never from the model). No tool accepts a customer id."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from agentlab.config import ROOT
from agentlab.tools import Tool, ToolError, ToolRegistry
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


def make_support_tools(conn: sqlite3.Connection, customer_id: int, actor: str = "agent:support",
                       variant: str = "v1") -> ToolRegistry:
    features = parse_variant(variant)
    if features:
        return _make_v2(conn, customer_id, actor, features)
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


# ---------------------------------------------------------------------------------------------- v2
# Implements docs/design/support-tools-v2.md (the learner's design). Same names and parameters as v1.
# Three independently switchable features, so each can be measured on its own (TEXTBOOK §1: one change per run):
#   desc    = descriptions and parameter docs from the design doc
#   errors  = structured errors {error, message, next_steps}, incl. argument-validation errors
#   returns = derived fields in results (dollars, days_since_delivery, customer_message)
# "v2" = all three; "v1+desc", "v1+desc+errors", ... = partial.
FEATURES = ("desc", "errors", "returns")


def parse_variant(variant: str) -> set[str]:
    if variant == "v1":
        return set()
    if variant == "v2":
        return set(FEATURES)
    base, *feats = variant.split("+")
    if base != "v1" or not feats or any(f not in FEATURES for f in feats):
        raise ValueError(f"unknown tool variant {variant!r}: use v1, v2, or v1+<{'|'.join(FEATURES)}>[+...]")
    return set(feats)


W = services.REFUND_WINDOW_DAYS
_REASON_DESC = ("Why the customer wants a refund: damaged = arrived broken, cracked, defective or stopped working; "
                "not_as_described = wrong item, missing parts, differs from the listing; changed_mind = no longer "
                "wanted; late_delivery = arrived much later than promised; other = anything else.")


def _dollars(cents: int | None) -> str | None:
    return None if cents is None else f"${cents / 100:,.2f}"


def _err_json(code: str, message: str, steps: list[str]) -> str:
    return json.dumps({"error": code, "message": message, "next_steps": steps})


def _next_steps(e: services.ShopError, kind: str, reason: str) -> list[str]:
    if e.code == "NOT_FOUND":
        return ["Ask the customer to double-check the order number.", "Call get_my_orders to list their recent orders."]
    if e.code == "INVALID":
        if "exceeds refundable" in e.message:
            return ["Call issue_refund again with amount_cents no higher than max_refundable_cents from "
                    "check_refund_eligibility."]
        return ["Fix the arguments as described and call the tool again."]
    steps: list[str] = []
    if kind == "refund":
        if reason in ("changed_mind", "other") and "days" in e.message:
            steps.append(f"If the item arrived damaged or defective, check eligibility again with reason='damaged' "
                         f"({services.DAMAGED_WINDOW_DAYS}-day window).")
        steps += ["Explain the reason to the customer in one or two sentences.", "Offer escalate_to_human if they disagree."]
    elif kind == "cancel":
        steps.append("Offer a refund after delivery, or escalation if the order is late.")
    else:
        steps.append("Explain the reason to the customer and offer escalate_to_human.")
    return steps


def _p(type_: str, description: str | None, **extra) -> dict:
    return {"type": type_, **({"description": description} if description else {}), **extra}


def _make_v2(conn: sqlite3.Connection, customer_id: int, actor: str, features: set[str]) -> ToolRegistry:
    desc, errors, returns = "desc" in features, "errors" in features, "returns" in features
    v1 = make_support_tools(conn, customer_id, actor)      # v1 descriptions as the fallback

    def d(name: str, text: str) -> str:
        return text if desc else v1.get(name).description

    def pd(text: str) -> str | None:
        return text if desc else None

    def guarded(fn, kind: str = ""):
        def run(**kw):
            try:
                return fn(**kw)
            except services.ShopError as e:
                if not errors:
                    raise
                raise ToolError(_err_json(e.code, e.message, _next_steps(e, kind, kw.get("reason", "")))) from None
        return run

    def get_my_orders(limit: int = 10):
        rows = services.list_orders_for_customer(conn, customer_id, limit)
        if not returns:
            return rows
        return [{"id": o["id"], "status": o["status"], "placed_on": o["placed_at"][:10],
                 "delivered_on": (o["delivered_at"] or "")[:10] or None, "total": _dollars(o["total_cents"]),
                 "total_cents": o["total_cents"]} for o in rows]

    def lookup_order(order_id: int):
        o = services.get_order(conn, order_id, customer_id=customer_id)
        if not returns:
            return o
        from shopfront import clock
        # why trimmed: return what the next decision needs, not the whole row (TEXTBOOK §3)
        return {"id": o["id"], "status": o["status"], "placed_on": o["placed_at"][:10],
                "shipped_on": (o["shipped_at"] or "")[:10] or None, "delivered_on": (o["delivered_at"] or "")[:10] or None,
                "days_since_delivery": (clock.now() - clock.parse(o["delivered_at"])).days if o["delivered_at"] else None,
                "business_days_in_transit": o.get("business_days_in_transit"),
                "items": [{"name": i["name"], "qty": i["qty"]} for i in o["items"]],
                "total": _dollars(o["total_cents"]), "total_cents": o["total_cents"],
                "refunds": [{"amount": _dollars(r["amount_cents"]), "status": r["status"]} for r in o["refunds"]]}

    def check(order_id: int, reason: str):
        return services.refund_eligibility(conn, order_id, reason, customer_id=customer_id)

    def refund(order_id: int, amount_cents: int, reason: str):
        r = services.issue_refund(conn, order_id, amount_cents, reason, actor=actor, customer_id=customer_id)
        if returns:
            amt = _dollars(amount_cents)
            r["customer_message"] = (f"Submitted {amt} for review; it is not refunded yet." if r["status"] == "pending_approval"
                                     else f"Refunded {amt} to the original payment method.")
        return r

    def cancel(order_id: int):
        return services.cancel_order(conn, order_id, actor, customer_id=customer_id)

    def escalate(summary: str, order_id: int | None = None):
        return services.escalate_to_human(conn, customer_id, summary, order_id, actor)

    order = lambda t: _p("integer", pd(t), minimum=1)  # noqa: E731
    reason = _p("string", pd(_REASON_DESC), enum=list(services.REFUND_REASONS))
    invalid = ((lambda name, problems: _err_json("INVALID", f"Invalid arguments for {name}: " + "; ".join(problems),
                                                 ["Fix the arguments as described and call the tool again."]))
               if errors else None)
    return ToolRegistry([
        Tool("get_my_orders", d("get_my_orders", "List this customer's most recent orders, newest first. Use only when "
             "the customer hasn't given an order number (if they have, use lookup_order directly). Returns up to `limit` "
             "orders with id, status, dates and total."),
             _obj({"limit": _p("integer", pd("How many orders to return (default 10)."), minimum=1, maximum=20)}, []),
             guarded(get_my_orders)),
        Tool("lookup_order", d("lookup_order", "Get one of this customer's orders by number. Use when the customer "
             "mentions an order number. Returns status, key dates, days since delivery, items, total and existing "
             "refunds. Orders on other accounts are reported as not found."),
             _obj({"order_id": order("The order number the customer gave, e.g. 4821.")}, ["order_id"]),
             guarded(lookup_order)),
        Tool("check_refund_eligibility", d("check_refund_eligibility", "Check whether an order can be refunded for a "
             "reason, applying the official policy windows (which differ by reason and membership tier). No side "
             "effects. Use before issue_refund, with the reason that matches what the customer said. Returns eligible, "
             "problems, window_days, days_since_delivery and max_refundable_cents."),
             _obj({"order_id": order("The order number, e.g. 4821."), "reason": reason}, ["order_id", "reason"]),
             guarded(check, "refund")),
        Tool("issue_refund", d("issue_refund", "Refund an order to the original payment method. Use only after "
             "check_refund_eligibility says eligible, with the same reason. Large refunds are queued for human approval "
             "and are not complete when this returns: tell the customer it is pending review. Returns refund_id, status "
             "(issued or pending_approval) and customer_message."),
             _obj({"order_id": order("The order to refund."),
                   "amount_cents": _p("integer", pd("Amount in cents, e.g. 4899 for $48.99; at most max_refundable_cents."),
                                      minimum=1),
                   "reason": reason}, ["order_id", "amount_cents", "reason"]),
             guarded(refund, "refund"), side_effects=True),
        Tool("cancel_order", d("cancel_order", "Cancel an order that hasn't shipped (status 'placed'). Use when the "
             "customer asks to cancel. Shipped orders cannot be cancelled; offer a refund after delivery or escalation if "
             "it's late. Returns the new status."),
             _obj({"order_id": order("The order to cancel.")}, ["order_id"]), guarded(cancel, "cancel"), side_effects=True),
        Tool("escalate_to_human", d("escalate_to_human", "Hand the case to a human teammate. Use for lost packages, "
             "warranty claims, safety issues (such as a swollen battery) or anything your tools can't resolve. Ask the "
             "customer first unless it's a safety issue. Returns a ticket id; a human replies within one business day."),
             _obj({"summary": _p("string", pd("What the customer needs and what you already checked, in 1-3 sentences."),
                                 minLength=10),
                   "order_id": order("The order concerned, if any.")}, ["summary"]),
             guarded(escalate), side_effects=True),
        Tool("search_help_center", d("search_help_center", "Search the help-center articles for policies and product "
             "care. Use for policy questions. Prefer articles with status 'current'; 'archived' articles describe old "
             "policies. Returns up to 3 articles with title, status, updated date and an excerpt."),
             _obj({"query": _p("string", pd("A few keywords, e.g. 'refund window'."), minLength=2)}, ["query"]),
             guarded(lambda query: search_help_center(query))),
    ], invalid_formatter=invalid)
