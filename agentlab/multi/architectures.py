"""Three ways to answer a breadth-heavy question (TEXTBOOK §2-§5):

  single:<A>                  one agent, every tool, one context
  orch:<LEAD>:<WORKER>        a lead that can only plan, delegate and answer; workers run IN PARALLEL, each with a
                              fresh context and tools scoped to its shard; their reports are reconciled before the
                              lead sees them
  mapreduce:<WORKER>:<RED>    a fixed workflow: code shards by category, one worker per shard with a fixed brief,
                              code retries missing shards once, one reducer call combines

Every run returns a MultiResult with the answer and what it cost: tokens per agent, the largest single prompt any
agent saw (context isolation is the point of workers), wall time, agents, calls, missing shards and conflicts.
"""
from __future__ import annotations

import contextvars
import json
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from agentlab.agent.loop import LoopConfig, run_agent
from agentlab.costs import Budget
from agentlab.llm.types import ChatModel, Message, to_dict
from agentlab.multi import reconcile as reconcile_module
from agentlab.multi.reconcile import WorkerReport
from agentlab.multi.tasks import MultiTask
from agentlab.multi.tools import analytics_tools, categories
from agentlab.tools.base import Tool, ToolRegistry
from agentlab.tools.errors import ToolError

SINGLE_SYSTEM = """\
You answer analytics questions about the Shopfront catalogue using read-only tools. Definitions in the question are
exact: follow them. Work systematically: list the categories, list each category's products, fetch stats in batches,
and keep track of what you have covered so nothing is skipped. Do arithmetic carefully (to pool an average over many
products, use rating_sum and review counts, not an average of averages). When you are sure, call submit_answer
exactly once with the answer in the shape the question asks for."""

LEAD_SYSTEM = """\
You lead a team of analyst workers answering an analytics question about the Shopfront catalogue. You cannot query
product data yourself: you can list categories, delegate work, and submit the answer.

delegate(tasks=[{shard, brief}]) runs one worker per task, in parallel. Each worker:
- sees ONLY its brief (not the question, not this conversation, not the other workers);
- can query only its shard (one category);
- returns a report: items (an object) and notes.
So each brief must be self-contained: the objective, the exact definitions and thresholds from the question, and
exactly what to put in items (keys and fields), e.g. "items: {SKU: {reviews, rating_sum, units_90d}} for every
product in the category". Key items by SKU (unique across shards), never by labels like "lowest". Ask for fields
that can be combined (counts and sums, not only averages). Delegate each shard at most once per call.

delegate returns the reconciled reports: results (merged items), missing_shards, conflicts, duplicates and notes.
If shards are missing, delegate them again (at most twice). Never guess data for a missing shard. When the results
cover every shard, compute the answer and call submit_answer exactly once, in the shape the question asks for."""

WORKER_SYSTEM = """\
You are an analyst worker with read-only tools scoped to one shard of the Shopfront catalogue. Do exactly what your
brief asks, for your shard only. Fetch what you need (product_stats takes up to 10 ids per call), then call report
exactly once with items shaped as the brief says and any caveats in notes. Report data from the tools, not
estimates. If something in your brief is impossible, report what you could and say so in notes."""

MAPREDUCE_BRIEF = """\
The overall question (answer it ONLY for category {shard}; other workers cover the other categories):
{question}

In report.items, give the facts your partial answer rests on, keyed by SKU, with the fields needed to combine partial
answers across categories: for every product that could matter, include reviews, rating_sum, avg_rating, units_90d,
stock, reorder_level and active. In notes, give your partial answer for {shard}."""

REDUCER_SYSTEM = """\
You combine workers' partial results into the final answer to an analytics question. Each worker covered one
category. Use only the data given. Follow the question's definitions exactly; pool averages with sums and counts.
Reply with JSON only: {"answer": <the answer in the shape the question asks for>}."""


# ------------------------------------------------------------------ metering
@dataclass
class CallRecord:
    agent: str
    input_tokens: int            # the whole prompt this call sent (cached or not): the agent's context size
    output_tokens: int


class Metered:
    """Wraps a ChatModel and records every call's prompt and output tokens, by agent. Thread-safe."""

    def __init__(self, inner: ChatModel, agent: str, log: list[CallRecord], lock: threading.Lock) -> None:
        self.inner, self.agent, self.log, self.lock = inner, agent, log, lock
        self.provider, self.model = inner.provider, inner.model

    def complete(self, **kw: Any):
        resp = self.inner.complete(**kw)
        with self.lock:
            self.log.append(CallRecord(self.agent, resp.usage.total_input, resp.usage.output_tokens))
        return resp


@dataclass
class MultiResult:
    arch: str
    answer: Any = None                       # None = no answer submitted
    cost_usd: float = 0.0
    latency_s: float = 0.0
    calls: list[CallRecord] = field(default_factory=list)
    agents: int = 0
    delegations: int = 0
    missing_shards: list[str] = field(default_factory=list)   # still missing when the answer was given
    conflicts: int = 0
    error: str | None = None
    provider_errors: int = 0                 # worker/lead/reducer failures caused by the provider (rate limits…)
    transcripts: dict[str, list] = field(default_factory=dict)   # agent -> messages (dicts), for `show`

    @property
    def input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def peak_context(self) -> int:
        """The largest prompt any single agent sent: what context isolation is supposed to keep small."""
        return max((c.input_tokens for c in self.calls), default=0)

    def tokens_by_role(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.calls:
            role = c.agent.split(":")[0]
            out[role] = out.get(role, 0) + c.input_tokens + c.output_tokens
        return out


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def _coerce(answer: Any) -> Any:
    # why: some models send structured arguments as a JSON string; accept it once, explicitly
    if isinstance(answer, str):
        try:
            return json.loads(answer)
        except ValueError:
            return answer
    return answer


def submit_tool(out: dict) -> Tool:
    def submit_answer(answer: Any):
        if "answer" in out:
            raise ToolError("You already submitted an answer. Stop now.")
        out["answer"] = _coerce(answer)
        return {"submitted": True}
    return Tool("submit_answer", "Submit the final answer, once, in the shape the question asks for (a JSON list or "
                "object, not prose). Returns {submitted: true}.",
                _obj({"answer": {"description": "the answer: a JSON array or object"}}, ["answer"]),
                submit_answer, side_effects=True)


# ------------------------------------------------------------------ workers
def run_worker(model: ChatModel, conn: sqlite3.Connection, shard: str, brief: str, budget: Budget | None,
               max_turns: int = 12) -> tuple[WorkerReport, list]:
    """One worker: a fresh context holding only its brief, tools scoped to its shard, and a report tool."""
    got: dict = {}

    def report(items: dict, notes: str = ""):
        if got:
            raise ToolError("You already reported. Stop now.")
        got.update(items=items, notes=notes)
        return {"received": True}

    reg = ToolRegistry([*analytics_tools(conn, [shard]), Tool(
        "report", "Report your results to the lead, once. items: an object shaped as your brief says; notes: "
        "caveats or partial-answer text. Returns {received: true}.",
        _obj({"items": {"type": "object", "description": "your results, shaped as the brief says"},
              "notes": {"type": "string", "description": "caveats, or your partial answer"}}, ["items"]),
        report, side_effects=True)])
    user = f"{brief}\n\nYour shard: category {shard!r}."
    r = run_agent(model, WORKER_SYSTEM, [Message.user(user)], reg,
                  LoopConfig(max_turns=max_turns, budget=budget, agent_name=f"worker-{shard}"))
    transcript = [to_dict(m) for m in r.messages]
    if not got:
        return WorkerReport(shard, {}, f"worker never reported (stop={r.stop})", ok=False), transcript
    return WorkerReport(shard, dict(got["items"]), str(got.get("notes", "")), ok=True), transcript


def run_workers(worker_factory: Callable[[], ChatModel], conn, tasks: list[tuple[str, str]], budget,
                log: list[CallRecord], lock: threading.Lock, transcripts: dict, tag: str, max_parallel: int = 6,
                worker_turns: int = 12) -> list[WorkerReport]:
    """Run (shard, brief) tasks in parallel. why: workers are independent, so wall time ~ the slowest worker,
    not the sum. A worker that crashes becomes an ok=False report, never an exception in the lead."""
    def one(i_task):
        i, (shard, brief) = i_task
        name = f"worker:{shard}#{tag}{i}"
        try:
            rep, tr = run_worker(Metered(worker_factory(), name, log, lock), conn, shard, brief, budget,
                                 worker_turns)
        except Exception as e:  # noqa: BLE001 - one worker's failure must not take down the others
            from agentlab.evals.runner import error_kind
            rep, tr = WorkerReport(shard, {}, f"worker failed: {type(e).__name__}: {e}", ok=False,
                                   error_kind=error_kind(e)), []
        with lock:
            transcripts[name] = tr
        return rep
    # why copy_context: threads don't inherit contextvars, so without it worker spans float free of the lead's
    # trace (Node 02 tracing); each worker gets its own copy of the caller's context
    with ThreadPoolExecutor(max_workers=max(1, min(max_parallel, len(tasks)))) as pool:
        return list(pool.map(lambda it: contextvars.copy_context().run(one, it), enumerate(tasks)))


# ------------------------------------------------------------------ architectures
def run_single(model: ChatModel, conn: sqlite3.Connection, task: MultiTask, budget: Budget | None = None,
               max_turns: int = 40) -> MultiResult:
    t0 = time.perf_counter()
    log: list[CallRecord] = []
    spent0 = budget.spent_usd if budget else 0.0
    out: dict = {}
    reg = ToolRegistry([*analytics_tools(conn), submit_tool(out)])
    res = MultiResult("single", agents=1)
    try:
        r = run_agent(Metered(model, "single", log, threading.Lock()), SINGLE_SYSTEM, [Message.user(task.question)],
                      reg, LoopConfig(max_turns=max_turns, budget=budget, agent_name="single"))
        res.transcripts = {"single": [to_dict(m) for m in r.messages]}
        if "answer" not in out:
            res.error = f"no answer submitted (stop={r.stop})"
    except Exception as e:  # noqa: BLE001 - keep the accounting of what was spent before the failure
        _record_failure(res, e)
    res.answer, res.calls = out.get("answer"), log
    res.cost_usd = (budget.spent_usd - spent0) if budget else 0.0
    res.latency_s = time.perf_counter() - t0
    return res


def _record_failure(res: MultiResult, e: Exception) -> None:
    from agentlab.costs import BudgetExceeded
    from agentlab.evals.runner import error_kind
    if isinstance(e, BudgetExceeded):
        raise e
    res.error = f"{type(e).__name__}: {e}"
    if error_kind(e) == "provider":
        res.provider_errors += 1


def run_orchestrator(lead: ChatModel, worker_factory: Callable[[], ChatModel], conn: sqlite3.Connection,
                     task: MultiTask, budget: Budget | None = None, max_turns: int = 12, max_delegations: int = 3,
                     max_parallel: int = 6, worker_turns: int = 12) -> MultiResult:
    t0 = time.perf_counter()
    log: list[CallRecord] = []
    lock = threading.Lock()
    spent0 = budget.spent_usd if budget else 0.0
    shards = categories(conn)
    out: dict = {}
    transcripts: dict[str, list] = {}
    state = {"delegations": 0, "agents": 1, "missing": list(shards), "covered": set(), "conflicts": 0,
             "provider_errors": 0}

    def delegate(tasks: list):
        if state["delegations"] >= max_delegations:
            raise ToolError(f"Delegation limit reached ({max_delegations}). Answer with what you have, and say "
                            "which shards are missing.")
        if not tasks:
            raise ToolError("tasks is empty: give at least one {shard, brief}.")
        if len(tasks) > len(shards):
            raise ToolError(f"At most {len(shards)} tasks per call (one per shard).")
        pairs = []
        for t in tasks:
            if not isinstance(t, dict) or not isinstance(t.get("shard"), str) or not isinstance(t.get("brief"), str):
                raise ToolError("Each task must be {shard: string, brief: string}.")
            if t["shard"] not in shards:
                raise ToolError(f"Unknown shard {t['shard']!r}. Shards are categories: {', '.join(shards)}.")
            if len(t["brief"].strip()) < 20:
                raise ToolError(f"The brief for {t['shard']} is too short to be self-contained: the worker sees "
                                "nothing but the brief.")
            if any(t["shard"] == p[0] for p in pairs):
                raise ToolError(f"Shard {t['shard']!r} appears twice in one delegation: give each shard one task.")
            pairs.append((t["shard"], t["brief"]))
        state["delegations"] += 1
        state["agents"] += len(pairs)
        reports = run_workers(worker_factory, conn, pairs, budget, log, lock, transcripts,
                              f"d{state['delegations']}.", max_parallel, worker_turns)
        state["provider_errors"] += sum(1 for r in reports if not r.ok and r.error_kind == "provider")
        rec = reconcile_module.reconcile([s for s, _ in pairs], reports)
        state["covered"] |= {s for s, _ in pairs if s not in rec.missing_shards}
        state["missing"] = [s for s in shards if s not in state["covered"]]
        state["conflicts"] += len(rec.conflicts)
        return {"results": rec.merged, "missing_shards": rec.missing_shards, "conflicts": rec.conflicts,
                "duplicates": rec.duplicates, "notes": rec.notes,
                "not_yet_covered": state["missing"]}

    lead_tools = [t for t in analytics_tools(conn) if t.name == "list_categories"]
    reg = ToolRegistry([*lead_tools, Tool(
        "delegate", "Run workers in parallel, one per task; each sees only its brief and can query only its shard "
        "(a category). Returns {results, missing_shards, conflicts, duplicates, notes, not_yet_covered}.",
        _obj({"tasks": {"type": "array", "description": "one {shard, brief} per worker",
                        "items": {"type": "object", "properties": {
                            "shard": {"type": "string", "description": "a category from list_categories"},
                            "brief": {"type": "string", "description": "self-contained instructions"}},
                            "required": ["shard", "brief"]}}}, ["tasks"]),
        delegate, side_effects=True), submit_tool(out)])
    res = MultiResult("orch", transcripts=transcripts)
    try:
        r = run_agent(Metered(lead, "lead", log, lock), LEAD_SYSTEM, [Message.user(task.question)], reg,
                      LoopConfig(max_turns=max_turns, budget=budget, agent_name="lead"))
        transcripts["lead"] = [to_dict(m) for m in r.messages]
        if "answer" not in out:
            res.error = f"no answer submitted (stop={r.stop})"
    except Exception as e:  # noqa: BLE001
        _record_failure(res, e)
    res.answer, res.calls, res.agents, res.delegations = out.get("answer"), log, state["agents"], state["delegations"]
    res.missing_shards, res.conflicts = state["missing"], state["conflicts"]
    res.provider_errors += state["provider_errors"]
    res.cost_usd = (budget.spent_usd - spent0) if budget else 0.0
    res.latency_s = time.perf_counter() - t0
    return res


def _parse_answer(text: str) -> Any:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        d = json.loads(text)
    except ValueError:
        return None
    return d.get("answer") if isinstance(d, dict) else None


def run_map_reduce(worker_factory: Callable[[], ChatModel], reducer: ChatModel, conn: sqlite3.Connection,
                   task: MultiTask, budget: Budget | None = None, max_parallel: int = 6,
                   worker_turns: int = 12) -> MultiResult:
    t0 = time.perf_counter()
    log: list[CallRecord] = []
    lock = threading.Lock()
    spent0 = budget.spent_usd if budget else 0.0
    shards = categories(conn)
    transcripts: dict[str, list] = {}
    pairs = [(s, MAPREDUCE_BRIEF.format(shard=s, question=task.question)) for s in shards]
    reports = run_workers(worker_factory, conn, pairs, budget, log, lock, transcripts, "m", max_parallel,
                          worker_turns)
    rec = reconcile_module.reconcile(shards, reports)
    agents, rounds = len(pairs), 1
    if rec.missing_shards:
        # why: the retry is a line of code, not a model's judgment call: deterministic, and visible in the result
        retry = [p for p in pairs if p[0] in rec.missing_shards]
        reports += run_workers(worker_factory, conn, retry, budget, log, lock, transcripts, "r", max_parallel,
                               worker_turns)
        agents, rounds = agents + len(retry), 2
        rec = reconcile_module.reconcile(shards, reports)
    payload = {"results": rec.merged, "partial_answers": rec.notes, "missing_shards": rec.missing_shards,
               "conflicts": rec.conflicts}
    user = f"Question: {task.question}\n\nWorker results (JSON):\n{json.dumps(payload, sort_keys=True)}"
    res = MultiResult("mapreduce", None, 0.0, 0.0, log, agents + 1, rounds, list(rec.missing_shards),
                      len(rec.conflicts), transcripts=transcripts)
    # provider failures among the workers that were finally missing
    final = {r.shard: r for r in reports}
    res.provider_errors = sum(1 for s in rec.missing_shards if final.get(s) and final[s].error_kind == "provider")
    m = Metered(reducer, "reducer", log, lock)
    try:
        if budget:
            budget.check()
        resp = m.complete(system=REDUCER_SYSTEM, messages=[Message.user(user)], tools=None, max_tokens=2048)
        if budget:
            budget.charge(reducer.model, resp.usage, provider=reducer.provider)
        transcripts["reducer"] = [to_dict(Message.user(user)), to_dict(Message("assistant", list(resp.content)))]
        res.answer = _parse_answer(resp.text)
        if res.answer is None:
            res.error = "reducer output unparseable"
    except Exception as e:  # noqa: BLE001
        _record_failure(res, e)
    res.cost_usd = (budget.spent_usd - spent0) if budget else 0.0
    res.latency_s = time.perf_counter() - t0
    return res


ARCH_HELP = "single:A | orch:LEAD:WORKER | mapreduce:WORKER:REDUCER  (A, LEAD, ... are aliases from models.toml)"


def parse_arch(spec: str) -> tuple[str, list[str]]:
    """An optional "@label" suffix names a variant (e.g. "orch:fast:fast@brief2") so two runs of the same
    architecture with different prompts can be compared in one report."""
    base, _, label = spec.partition("@")
    if "@" in spec and not label:
        raise ValueError(f"bad architecture {spec!r}: empty @label")
    name, *args = base.split(":")
    if not ((name == "single" and len(args) == 1) or (name in ("orch", "mapreduce") and len(args) == 2)) \
            or not all(args):
        raise ValueError(f"bad architecture {spec!r}: {ARCH_HELP}")
    return name, args


def run_arch(spec: str, task: MultiTask, get_model: Callable[[str], ChatModel], conn: sqlite3.Connection,
             budget: Budget | None = None, max_parallel: int = 6) -> MultiResult:
    name, args = parse_arch(spec)
    if name == "single":
        res = run_single(get_model(args[0]), conn, task, budget)
    elif name == "orch":
        res = run_orchestrator(get_model(args[0]), lambda: get_model(args[1]), conn, task, budget,
                               max_parallel=max_parallel)
    else:
        res = run_map_reduce(lambda: get_model(args[0]), get_model(args[1]), conn, task, budget,
                             max_parallel=max_parallel)
    res.arch = spec
    return res
