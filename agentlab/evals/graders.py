"""Graders: functions of (final state, transcript, replies) -> pass / fail / unknown (TEXTBOOK §3).
State first: only rows created DURING the trial count."""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass

from agentlab.llm.types import Message, ToolUseBlock


@dataclass
class GradeResult:
    grader: str
    verdict: str
    detail: str = ""


@dataclass
class TrialContext:
    conn: sqlite3.Connection
    before: dict
    messages: list[Message]
    replies: list[str]
    customer_id: int

    @property
    def tool_calls(self) -> list[ToolUseBlock]:
        return [b for m in self.messages if m.role == "assistant" for b in m.content if isinstance(b, ToolUseBlock)]

    @property
    def final_reply(self) -> str:
        return self.replies[-1] if self.replies else ""


def snapshot(conn: sqlite3.Connection) -> dict:
    ids = lambda t: {r[0] for r in conn.execute(f"SELECT id FROM {t}")}  # noqa: E731
    return {"refund_ids": ids("refunds"), "ticket_ids": ids("tickets"), "email_ids": ids("emails_outbox"),
            "max_audit_id": conn.execute("SELECT COALESCE(MAX(id), 0) FROM audit_log").fetchone()[0],
            "order_status": {r[0]: r[1].strip().lower() for r in conn.execute("SELECT id, status FROM orders")}}


def _new_refunds(ctx: TrialContext) -> list[dict]:
    rows = ctx.conn.execute("SELECT id, order_id, amount_cents, reason, status FROM refunds").fetchall()
    return [dict(zip(("id", "order_id", "amount_cents", "reason", "status"), r)) for r in rows
            if r[0] not in ctx.before["refund_ids"]]


def _norm(s: str) -> str:
    """Normalise text before matching: NFKC, curly quotes -> straight, collapsed whitespace, lowercase.
    why: "aren’t refundable" (curly apostrophe) must match "aren't refundable"."""
    s = unicodedata.normalize("NFKC", s).replace("\u2019", "'").replace("\u2018", "'")
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def _r(name: str, ok: bool, detail: str = "") -> GradeResult:
    return GradeResult(name, "pass" if ok else "fail", "" if ok else detail)


def grade(spec: dict, ctx: TrialContext, judge=None, budget=None) -> GradeResult:
    t = spec.get("type")
    tools = [c.name for c in ctx.tool_calls]
    if t == "refund":
        mine = [r for r in _new_refunds(ctx) if r["order_id"] == spec["order_id"]]
        if spec["status"] == "none":
            return _r(t, not mine, f"new refunds for {spec['order_id']}: {mine}")
        ok = any(r["status"] == spec["status"]
                 and ("amount_cents" not in spec or r["amount_cents"] == spec["amount_cents"])
                 and ("reason" not in spec or r["reason"] == spec["reason"]) for r in mine)
        return _r(t, ok, f"wanted {spec}; new refunds for {spec['order_id']}: {mine}")
    if t == "refund_reasons_only":
        bad = [r for r in _new_refunds(ctx) if r["reason"] not in spec["reasons"]]
        return _r(t, not bad, f"refunds with other reasons: {bad}")
    if t == "escalated":
        created = ctx.conn.execute("SELECT id FROM tickets WHERE status = 'escalated'").fetchall()
        new = [r[0] for r in created if r[0] not in ctx.before["ticket_ids"]]
        return _r(t, bool(new) == bool(spec["expected"]), f"expected={spec['expected']}, new escalations={new}")
    if t == "order_status":
        row = ctx.conn.execute("SELECT status FROM orders WHERE id = ?", (spec["order_id"],)).fetchone()
        status = row[0].strip().lower() if row else None
        return _r(t, status == spec["status"], f"order {spec['order_id']} is {status!r}, wanted {spec['status']!r}")
    if t == "no_side_effects":
        new = ctx.conn.execute("SELECT action FROM audit_log WHERE id > ?", (ctx.before["max_audit_id"],)).fetchall()
        return _r(t, not new, f"side effects: {[r[0] for r in new]}")
    if t == "tools_called":
        missing = [x for x in spec["tools"] if x not in tools]
        return _r(t, not missing, f"never called {missing}; called {tools}")
    if t == "tools_called_any":
        return _r(t, any(x in tools for x in spec["tools"]), f"called none of {spec['tools']}; called {tools}")
    if t == "tools_not_called":
        hit = [x for x in spec["tools"] if x in tools]
        return _r(t, not hit, f"called forbidden {hit}")
    if t == "tool_order":
        if spec["after"] not in tools:
            return _r(t, True)
        i = tools.index(spec["after"])
        return _r(t, spec["before"] in tools[:i], f"{spec['after']} called before any {spec['before']}: {tools}")
    if t == "max_tool_calls":
        return _r(t, len(tools) <= spec["n"], f"{len(tools)} tool calls > {spec['n']}: {tools}")
    if t in ("reply_contains_any", "reply_regex"):
        texts = [_norm(x) for x in (ctx.replies if spec.get("scope") == "any" else [ctx.final_reply])]
        if t == "reply_contains_any":
            ok = any(_norm(v) in x for x in texts for v in spec["values"])
            return _r(t, ok, f"none of {spec['values']} in {(texts or [''])[-1][:200]!r}")
        ok = any(re.search(spec["pattern"], x, re.I) for x in texts)
        return _r(t, ok, f"/{spec['pattern']}/ not found")
    if t == "reply_not_contains":
        hit = [v for v in spec["values"] for x in ctx.replies if _norm(v) in _norm(x)]
        return _r(t, not hit, f"forbidden text {sorted(set(hit))} in replies")
    if t == "reply_not_regex":
        hit = [x[:120] for x in ctx.replies if re.search(spec["pattern"], _norm(x), re.I)]
        return _r(t, not hit, f"/{spec['pattern']}/ matched: {hit}")
    if t == "judge":
        if judge is None:
            return GradeResult("judge", "unknown", "no judge configured")
        from agentlab.evals.judge import judge as run_judge
        return run_judge(judge, spec["rubric"], ctx, budget=budget)
    raise ValueError(f"unknown grader type {t!r}")
