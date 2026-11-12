"""The chaos lab (TEXTBOOK §7): the same support tasks under injected provider faults and process crashes, run
three ways, and measured by what the CUSTOMER and the BUSINESS would see.

  naive    the Node 02 loop as is: a provider error or a crash ends the run
  retry    + ResilientModel (backoff, Retry-After): survives flaky providers, not crashes
  durable  + the journal and recovery: crashes are resumed, side effects reconciled instead of repeated
"""
from __future__ import annotations

import json
import random
import sqlite3
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from agentlab.agent.loop import LoopConfig, run_agent
from agentlab.costs import Budget, BudgetExceeded
from agentlab.llm.types import ChatModel, Message
from agentlab.reliability.durable import DurableAgent, run_until_done
from agentlab.reliability.faults import Crash, FaultyModel
from agentlab.reliability.journal import Journal
from agentlab.reliability.resilient import ResilientModel

CONFIGS = ("naive", "retry", "requeue", "durable")
MAX_REQUEUES = 3            # requeue: how many times a lost job is run again from the top
MAX_RESUMES = 10            # durable: how many times a crashed run is resumed


@dataclass(frozen=True)
class Scenario:
    id: str
    customer_id: int
    message: str
    refund_order: int | None          # the order that should end up with exactly one refund (None: no refund)


SCENARIOS = [
    Scenario("damaged", 9001, "The lid on my dutch oven from order 4821 arrived cracked. Please refund it.", 4821),
    Scenario("changed_mind", 9001, "I changed my mind about order 4822. Please refund it.", 4822),
    Scenario("plus", 9002, "Please refund order 4823, I don't need it after all.", 4823),
    Scenario("where", 9003, "Where is my order 4824? It's been weeks.", None),
    Scenario("big", 9006, "Order 4826 isn't what I wanted, please refund it.", 4826),
]


def shop_reconcilers(conn: sqlite3.Connection, customer_id: int | None = None) -> dict:
    """How to tell, after a crash, whether a side effect already happened (TEXTBOOK §4). Each returns what the
    tool would have returned if it did, else None (then it's safe to run). Scoped to the customer when given, so a
    refund someone else made can't be passed off as this run's."""
    own = "" if customer_id is None else " AND o.customer_id = ?"
    who = () if customer_id is None else (customer_id,)

    def refund(args: dict):
        r = conn.execute("SELECT r.id, r.status, r.amount_cents FROM refunds r JOIN orders o ON o.id = r.order_id "
                         f"WHERE r.order_id = ?{own} ORDER BY r.id DESC LIMIT 1",
                         (args.get("order_id"), *who)).fetchone()
        return None if r is None else {"refund_id": r[0], "status": r[1], "amount_cents": r[2],
                                       "note": "This refund already exists (recovered after a restart)."}

    def cancel(args: dict):
        r = conn.execute(f"SELECT o.status FROM orders o WHERE o.id = ?{own}", (args.get("order_id"), *who)).fetchone()
        if r and r[0].strip().lower() == "cancelled":
            return {"order_id": args.get("order_id"), "status": "cancelled",
                    "note": "Refunded in full within 3 business days."}      # what cancel_order itself returns
        return None

    def escalate(args: dict):
        # services.escalate_to_human stores the summary as the ticket body
        q = "SELECT id FROM tickets WHERE body = ? AND channel = 'chat'"
        params: tuple = (args.get("summary"),)
        if customer_id is not None:
            q, params = q + " AND customer_id = ?", params + (customer_id,)
        r = conn.execute(q + " ORDER BY id DESC LIMIT 1", params).fetchone()
        return None if r is None else {"ticket_id": r[0], "status": "escalated",
                                       "note": "already escalated (recovered after a restart)"}
    return {"issue_refund": refund, "cancel_order": cancel, "escalate_to_human": escalate}


@dataclass
class ChaosResult:
    scenario: str
    config: str
    seed: int
    completed: bool = False           # the customer got an answer
    refund_ok: bool = False           # exactly the expected refunds exist
    refunds: int = 0
    duplicate_attempts: int = 0       # refund calls that hit "already exists": a side effect tried again
    injected: list[str] = field(default_factory=list)
    crashes: int = 0
    resumes: int = 0                  # durable: resumes; requeue: reruns from the top
    retries: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    error: str | None = None
    final_text: str = ""


class Crasher:
    """Kills the 'process' with probability `rate` at each crash point (deterministic per seed)."""

    def __init__(self, rate: float, seed: int) -> None:
        self.rate, self.rng, self.crashes = rate, random.Random(seed), 0

    def maybe(self) -> None:
        if self.rng.random() < self.rate:
            self.crashes += 1
            raise Crash("injected crash")


def _support(conn, customer_id):
    from agentlab.assistant.prompts import get_prompt
    from agentlab.assistant.tools import make_support_tools
    from shopfront import clock
    return (get_prompt("v2").replace("{today}", clock.now().date().isoformat()),
            make_support_tools(conn, customer_id, actor="agent:chaos", variant="v2"))


def run_one(s: Scenario, config: str, model: ChatModel, conn: sqlite3.Connection, *, fault_rate: float,
            crash_rate: float, seed: int, budget: Budget | None = None, sleep=time.sleep) -> ChaosResult:
    t0 = time.perf_counter()
    res = ChaosResult(s.id, config, seed)
    faulty = FaultyModel(model, rate=fault_rate, seed=seed)
    crasher = Crasher(crash_rate, seed)
    system, tools = _support(conn, s.customer_id)
    spent0 = budget.spent_usd if budget else 0.0
    m = faulty if config == "naive" else ResilientModel(faulty, sleep=sleep, cap=4.0)
    try:
        if config in ("naive", "retry", "requeue"):
            class CrashyTools:              # a crash right after a tool ran: the side effect happened, the reply didn't
                def specs(self):
                    return tools.specs()

                def execute(self, call):
                    r = tools.execute(call)
                    crasher.maybe()
                    return r
            attempts = 1 + (MAX_REQUEUES if config == "requeue" else 0)
            for attempt in range(attempts):
                try:
                    # requeue: like a job queue, a lost job runs again FROM THE TOP, with a fresh transcript
                    r = run_agent(m, system, [Message.user(s.message)], CrashyTools(),
                                  LoopConfig(max_turns=8, budget=budget, agent_name=f"chaos-{config}"))
                except (Crash, Exception):  # noqa: BLE001 - this attempt is lost
                    if attempt == attempts - 1:
                        raise
                    res.resumes += 1
                    continue
                if r.stop == "budget":
                    raise BudgetExceeded("chaos: budget reached")   # run_agent reports it; the lab must stop
                res.duplicate_attempts += sum(c.name == "issue_refund" and "already exists" in c.result_preview
                                              for c in r.tool_calls)
                res.completed = r.stop == "end_turn" and bool(r.final_text.strip())
                res.final_text = r.final_text
                break
        else:
            with tempfile.TemporaryDirectory() as tmp:
                j = Journal(Path(tmp) / "journal.db")
                agent = DurableAgent(j, tools, reconcilers=shop_reconcilers(conn, s.customer_id),
                                     hook=lambda point, info: crasher.maybe() if point in ("journaled", "executed")
                                     and info.get("kind") != "start" else None)
                run_id = f"{s.id}-{seed}"
                try:
                    try:
                        out = agent.start(run_id, m, system, [Message.user(s.message)], budget=budget, max_turns=8)
                    except BudgetExceeded:
                        raise
                    except (Crash, Exception):  # noqa: BLE001 - the first attempt died: recover like a restarted worker
                        res.resumes = 1
                        out, more = run_until_done(agent, run_id, m, budget=budget, max_resumes=MAX_RESUMES - 1,
                                                   sleep=sleep)
                        res.resumes += more
                    res.completed = out.status == "done" and bool(out.final_text.strip())
                    res.final_text = out.final_text
                except BaseException as e:
                    res.resumes += getattr(e, "resumes", 0)
                    raise
                finally:
                    res.duplicate_attempts = sum(1 for e in j.entries(run_id) if e["kind"] == "result"
                                                 and "already exists" in e["content"] and not e.get("reconciled"))
                    j.close()
    except BudgetExceeded:
        raise
    except (Crash, Exception) as e:  # noqa: BLE001 - the run is lost
        res.error = f"{type(e).__name__}: {e}"
    if s.refund_order is not None:
        res.refunds = conn.execute("SELECT COUNT(*) FROM refunds WHERE order_id = ?", (s.refund_order,)).fetchone()[0]
    else:
        res.refunds = conn.execute("SELECT COUNT(*) FROM refunds WHERE actor = 'agent:chaos'").fetchone()[0]
    res.refund_ok = res.refunds == (1 if s.refund_order is not None else 0)
    res.injected, res.crashes = list(faulty.injected), crasher.crashes
    res.retries = getattr(m, "retries", 0)
    res.cost_usd = (budget.spent_usd - spent0) if budget else 0.0
    res.latency_s = time.perf_counter() - t0
    return res


def run_chaos(model_factory: Callable[[], ChatModel], conn_factory: Callable, *, configs=CONFIGS,
              scenarios=SCENARIOS, seeds=(0, 1, 2), fault_rate: float = 0.2, crash_rate: float = 0.1,
              budget: Budget | None = None, out: Path | None = None, sleep=time.sleep) -> list[ChaosResult]:
    results = []
    if out:
        (out / "results.jsonl").write_text("")
    for seed in seeds:
        for s in scenarios:
            for c in configs:
                conn = conn_factory()
                try:
                    r = run_one(s, c, model_factory(), conn, fault_rate=fault_rate, crash_rate=crash_rate,
                                seed=seed, budget=budget, sleep=sleep)
                finally:
                    conn.close()
                results.append(r)
                if out:
                    with open(out / "results.jsonl", "a") as f:
                        f.write(json.dumps(asdict(r)) + "\n")
    return results


def summarize(results: list[ChaosResult]) -> dict[str, dict]:
    by: dict[str, list[ChaosResult]] = {}
    for r in results:
        by.setdefault(r.config, []).append(r)
    rate = lambda xs: sum(xs) / len(xs) if xs else 0.0  # noqa: E731
    return {c: {"n": len(rs), "completed": rate([r.completed for r in rs]),
                "refund_ok": rate([r.refund_ok for r in rs]),
                "silent": sum(r.refunds > 0 and not r.completed for r in rs),
                "duplicate_attempts": sum(r.duplicate_attempts for r in rs),
                "faults": sum(len(r.injected) for r in rs), "crashes": sum(r.crashes for r in rs),
                "resumes": sum(r.resumes for r in rs), "retries": sum(r.retries for r in rs),
                "cost": sum(r.cost_usd for r in rs) / len(rs), "p50_s": sorted(r.latency_s for r in rs)[len(rs) // 2]}
            for c, rs in by.items()}


def render(results: list[ChaosResult]) -> str:
    s = summarize(results)
    rows = ["| config | runs | customer got an answer | refunds correct | refunded but no answer | "
            "retried side effects | faults injected | crashes | resumes | retries | $/run | p50 s |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c, v in s.items():
        rows.append(f"| {c} | {v['n']} | {v['completed']:.0%} | {v['refund_ok']:.0%} | {v['silent']} | "
                    f"{v['duplicate_attempts']} | {v['faults']} | {v['crashes']} | {v['resumes']} | {v['retries']} | "
                    f"{v['cost']:.4f} | {v['p50_s']:.1f} |")
    return "\n".join(rows) + "\n\n\"refunded but no answer\": money moved, the customer was never told.\n"
