"""Run tasks x models x trials, each trial in a fresh environment (TEXTBOOK §2)."""
from __future__ import annotations

import json
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from agentlab.assistant.support import SupportAssistant
from agentlab.costs import Budget, BudgetExceeded
from agentlab.evals.graders import GradeResult, TrialContext, grade, snapshot
from agentlab.evals.task import Task
from agentlab.evals.user_sim import SimulatedUser
from agentlab.llm.types import ChatModel
from shopfront import db

MAX_SIM_TURNS = 12
PROVIDER_ERROR_MODULES = ("anthropic", "openai", "httpx", "httpcore")
PROVIDER_ERROR_WORDS = ("RateLimit", "Timeout", "Connection", "Overloaded", "InternalServer", "ServiceUnavailable")


def error_kind(e: BaseException) -> str:
    """'provider' for infrastructure failures (rate limits, timeouts, 5xx), 'agent' for everything else.
    why: a 429 after retries is not the model failing the task; counting it as a fail turns provider noise into
    a quality difference (TEXTBOOK §2)."""
    mod = type(e).__module__.split(".")[0]
    name = type(e).__name__
    return "provider" if mod in PROVIDER_ERROR_MODULES or any(w in name for w in PROVIDER_ERROR_WORDS) else "agent"


@dataclass
class Trial:
    task_id: str
    trial: int
    model: str
    verdict: str
    grades: list[GradeResult]
    replies: list[str]
    tool_calls: list[str]
    transcript: list[dict]
    cost_usd: float
    latency_s: float
    turns: int
    stops: list[str]
    error: str | None
    tags: list[str]
    split: str
    error_kind: str | None = None       # "provider" | "agent" | "timeout" | None
    overhead_usd: float = 0.0           # judge + simulator spend (not the agent's)
    extra: dict = field(default_factory=dict)   # Node 06: per-turn token stats, context actions, memory writes


def run_trial(task: Task, model: ChatModel, *, template_db: Path, trial: int = 0, model_label: str | None = None,
              budget: Budget | None = None, judge_factory=None, sim_factory=None,
              assistant_opts: dict | None = None, ceiling_s: float = 600.0) -> Trial:
    tmp = Path(tempfile.mkdtemp(prefix=f"trial-{task.id}-"))
    conn = db.connect(db.snapshot(template_db, tmp / "shop.db"))
    spent0 = budget.spent_usd if budget else 0.0
    replies: list[str] = []
    stops: list[str] = []
    turns = 0
    error = None
    kind = None
    sim = None
    t0 = time.perf_counter()
    n_turns = sum(map(len, task.sessions)) if task.sessions else len(task.turns)
    ceiling = ceiling_s * max(1.0, n_turns / 10)     # why: a 50-turn chat legitimately takes 5x a 10-turn one
    transcript: list = []
    turn_stats: list[dict] = []
    memory_log: list[dict] = []
    session_starts: list[int] = []
    closed: set[int] = set()
    fixed: dict = {}
    assistant = None
    try:
        before = snapshot(conn)
        assistant = SupportAssistant(model, conn, task.customer_id, budget=budget, **(assistant_opts or {}))

        def close_session() -> None:
            # fold this session's record into the trial, then run the memory write path (if enabled)
            if assistant is None or id(assistant) in closed:
                return
            closed.add(id(assistant))
            transcript.extend(assistant.transcript)
            turn_stats.extend(dict(s, session=len(session_starts) - 1) for s in assistant.turn_stats)
            fixed.update(getattr(assistant, "fixed_tokens", {}))
            for w in (assistant.end_session() if hasattr(assistant, "end_session") else []):
                # everything needed to tell an extractor mistake from a policy mistake (YOU_DO task 8)
                memory_log.append({"session": len(session_starts) - 1, "kind": w.candidate.kind,
                                   "text": w.candidate.text, "evidence": w.candidate.evidence,
                                   "supersedes": w.candidate.supersedes, "action": w.decision.action,
                                   "reason": w.decision.reason, "memory_id": w.memory_id})

        def say(text: str) -> str:
            nonlocal turns
            r = assistant.chat(text)
            replies.append(r.reply)
            stops.append(r.result.stop)
            turns += r.result.turns
            return r.reply

        try:
            if task.sessions:
                for i, session in enumerate(task.sessions):
                    if i:
                        assistant = SupportAssistant(model, conn, task.customer_id, budget=budget,
                                                     **(assistant_opts or {}))
                    session_starts.append(len(replies))
                    for msg in session:
                        say(msg)
                        if time.perf_counter() - t0 > ceiling:
                            raise TimeoutError(f"trial exceeded the {ceiling:.0f}s ceiling")
                    close_session()
            elif task.turns:
                session_starts.append(0)
                for msg in task.turns:
                    say(msg)
                    if time.perf_counter() - t0 > ceiling:
                        raise TimeoutError(f"trial exceeded the {ceiling:.0f}s ceiling")
            else:
                session_starts.append(0)
                sim = SimulatedUser(sim_factory(), budget=budget, **task.user_sim)
                msg = sim.first_message()
                for _ in range(MAX_SIM_TURNS):
                    msg = sim.reply(say(msg))
                    if msg is None or time.perf_counter() - t0 > ceiling:
                        break
        except BudgetExceeded:
            raise                       # the run's cap is reached: stop everything, don't record a fake failure
        except TimeoutError as e:
            error, kind = f"TimeoutError: {e}", "timeout"
        except Exception as e:  # noqa: BLE001
            error, kind = f"{type(e).__name__}: {e}", error_kind(e)
        if budget is not None and "budget" in stops:
            # the loop turns a budget hit into stop="budget"; for an eval run that means the cap is reached
            raise BudgetExceeded(f"eval budget exhausted during task {task.id} (${budget.spent_usd:.4f})")
        try:                                # fold the last (or interrupted) session; no-op if already closed
            close_session()
        except BudgetExceeded:
            raise
        except Exception as e:  # noqa: BLE001
            error, kind = error or f"{type(e).__name__}: {e}", kind or error_kind(e)
        latency = time.perf_counter() - t0
        last = replies[session_starts[-1]:] if session_starts else replies
        ctx = TrialContext(conn, before, transcript, replies, task.customer_id, last_session_replies=last)
        judge = judge_factory() if judge_factory else None
        judge_spent0 = budget.spent_usd if budget else 0.0
        grades = []
        seen: dict[str, int] = {}
        for spec in task.graders:
            g = grade(spec, ctx, judge=judge, budget=budget)
            seen[g.grader] = seen.get(g.grader, 0) + 1
            if seen[g.grader] > 1:
                g.grader = f"{g.grader}#{seen[g.grader]}"
            grades.append(g)
        judge_spent = (budget.spent_usd - judge_spent0) if budget else 0.0
        verdicts = {g.verdict for g in grades}
        verdict = ("error" if error else "fail" if "fail" in verdicts else "unknown" if "unknown" in verdicts
                   else "pass")
        sim_spent = sim.spent_usd if sim else 0.0
        total = (budget.spent_usd - spent0) if budget else 0.0
        return Trial(task.id, trial, model_label or model.model, verdict, grades, replies,
                     [c.name for c in ctx.tool_calls], [m.to_dict() for m in transcript],
                     total - sim_spent - judge_spent, latency, turns, stops, error, list(task.tags), task.split,
                     kind, sim_spent + judge_spent,
                     {"turn_stats": turn_stats, "memory_writes": memory_log, "fixed_tokens": fixed,
                      "context_actions": sorted({s["action"] for s in turn_stats} - {"none"})})
    finally:
        conn.close()
        shutil.rmtree(tmp, ignore_errors=True)


def _dump(t: Trial) -> str:
    return json.dumps(asdict(t), default=str)


def load_trials(path: str | Path) -> list[Trial]:
    out = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            d["grades"] = [GradeResult(**g) for g in d["grades"]]
            out.append(Trial(**d))
    return out


def run_eval(tasks: list[Task], model_factories: dict[str, Callable[[], ChatModel]], *, template_db: Path,
             trials: int = 3, budget: Budget | None = None, judge_factory=None, sim_factory=None,
             assistant_opts: dict | None = None, out_dir: Path | None = None, meta_extra: dict | None = None,
             retry_provider_errors: bool = False) -> list[Trial]:
    if out_dir:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        import hashlib
        meta = {"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "models": list(model_factories), "trials": trials,
                "task_ids": [t.id for t in tasks],
                "tasks_sha256": hashlib.sha256(json.dumps([asdict(t) for t in tasks], sort_keys=True).encode()).hexdigest(),
                "assistant_opts_sha256": {k: hashlib.sha256(str(v).encode()).hexdigest()[:16]
                                          for k, v in (assistant_opts or {}).items()},
                **(meta_extra or {})}
        (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    results: list[Trial] = []
    # why this order: trial-major, then task, then model, so every model's trials are spread over the run
    # rather than one model running entirely in a slow hour (infrastructure noise, TEXTBOOK §2)
    for k in range(trials):
        for task in tasks:
            for label, factory in model_factories.items():
                t = run_trial(task, factory(), template_db=template_db, trial=k, model_label=label, budget=budget,
                              judge_factory=judge_factory, sim_factory=sim_factory, assistant_opts=assistant_opts)
                if retry_provider_errors and t.error_kind in ("provider", "timeout"):
                    time.sleep(5)
                    t = run_trial(task, factory(), template_db=template_db, trial=k, model_label=label,
                                  budget=budget, judge_factory=judge_factory, sim_factory=sim_factory,
                                  assistant_opts=assistant_opts)
                results.append(t)
                print(f"[{k}] {task.id:24} {label:12} {t.verdict:7} ${t.cost_usd:.4f} {t.latency_s:5.1f}s")
                if out_dir:
                    with open(out_dir / "trials.jsonl", "a") as f:
                        f.write(_dump(t) + "\n")
    return results
