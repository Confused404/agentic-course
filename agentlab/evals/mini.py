"""A minimal eval runner (Node 02). Outcomes are graded from the DATABASE, not the agent's prose (TEXTBOOK §8).
Node 04 replaces this with a real harness (trials, statistics, judges, CI tiers)."""
from __future__ import annotations

import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from agentlab.assistant.support import SupportAssistant
from agentlab.costs import Budget
from agentlab.llm.types import ChatModel
from shopfront import db


@dataclass
class Case:
    id: str
    customer_id: int
    turns: list[str]
    expect: dict
    note: str = ""


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    checks: dict[str, bool]
    transcript: list[dict]
    tools_called: list[str]
    cost_usd: float
    error: str | None = None
    final_reply: str = ""


def load_cases(path: str | Path) -> list[Case]:
    return [Case(**c) for c in yaml.safe_load(Path(path).read_text())]


def _count(conn: sqlite3.Connection, sql: str, *args) -> int:
    return conn.execute(sql, args).fetchone()[0]


def _snapshot_state(conn: sqlite3.Connection) -> dict:
    return {"refund_ids": {r[0] for r in conn.execute("SELECT id FROM refunds")},
            "escalations": _count(conn, "SELECT count(*) FROM tickets WHERE status = 'escalated'")}


def _evaluate(expect: dict, conn: sqlite3.Connection, before: dict, tools_called: list[str], reply: str) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    new_refunds = [dict(r) for r in conn.execute("SELECT * FROM refunds") if r["id"] not in before["refund_ids"]]
    low = reply.lower()
    for key, want in expect.items():
        if key == "tools_called":
            checks[key] = all(t in tools_called for t in want)
        elif key == "tools_not_called":
            checks[key] = not any(t in tools_called for t in want)
        elif key == "refund":
            # why: only refunds created DURING the case count; 4828 already has one from the seed
            mine = [r for r in new_refunds if r["order_id"] == want["order_id"]]
            if want["status"] == "none":
                checks[key] = not mine
            else:
                checks[key] = any(r["status"] == want["status"] for r in mine)
        elif key == "refund_reasons_only":
            checks[key] = all(r["reason"] in want for r in new_refunds)
        elif key == "escalated":
            created = _count(conn, "SELECT count(*) FROM tickets WHERE status='escalated'") > before["escalations"]
            checks[key] = created == bool(want)
        elif key == "order_status":
            row = conn.execute("SELECT status FROM orders WHERE id=?", (want["order_id"],)).fetchone()
            checks[key] = bool(row) and row[0].strip().lower() == want["status"]
        elif key == "reply_contains_any":
            checks[key] = any(s.lower() in low for s in want)
        elif key == "reply_not_contains":
            checks[key] = not any(s.lower() in low for s in want)
        else:
            raise ValueError(f"unknown expect key {key!r}")
    return checks


def run_case(case: Case, model: ChatModel, *, template_db: Path, budget: Budget | None = None,
             workdir: Path | None = None) -> CaseResult:
    # why: a fresh copy of the seeded DB per case, so one case's refund can't change another's result
    tmpdir = tempfile.mkdtemp(prefix=f"eval-{case.id}-", dir=workdir)
    path = db.snapshot(template_db, Path(tmpdir) / "shop.db")
    conn = db.connect(path)
    spent_before = budget.spent_usd if budget else 0.0
    try:
        before = _snapshot_state(conn)
        assistant = SupportAssistant(model, conn, case.customer_id, budget=budget)
        error, reply = None, ""
        try:
            for turn in case.turns:
                reply = assistant.chat(turn).reply
        except Exception as e:  # noqa: BLE001 - a failing model call fails the case, not the suite
            error = f"{type(e).__name__}: {e}"
        tools_called = [b.name for m in assistant.messages if m.role == "assistant"
                        for b in m.content if getattr(b, "type", "") == "tool_use"]
        checks = _evaluate(case.expect, conn, before, tools_called, reply)
        return CaseResult(case.id, error is None and all(checks.values()), checks,
                          [m.to_dict() for m in assistant.messages], tools_called,
                          (budget.spent_usd - spent_before) if budget else 0.0, error, reply)
    finally:
        conn.close()


def run_suite(cases: list[Case], model_factory: Callable[[], ChatModel], *, template_db: Path,
              budget: Budget | None = None, trials: int = 1) -> list[CaseResult]:
    return [run_case(c, model_factory(), template_db=template_db, budget=budget)
            for _ in range(trials) for c in cases]


def summarize(results: list[CaseResult]) -> dict:
    n = len(results)
    passed = sum(r.passed for r in results)
    names = sorted({k for r in results for k in r.checks})
    by_check = {k: sum(r.checks[k] for r in results if k in r.checks) / max(1, sum(k in r.checks for r in results))
                for k in names}
    return {"cases": n, "passed": passed, "pass_rate": passed / n if n else 0.0,
            "cost_usd": sum(r.cost_usd for r in results), "by_check": by_check}
