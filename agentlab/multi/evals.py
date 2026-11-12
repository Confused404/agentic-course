"""Comparing architectures (TEXTBOOK §6): correctness against SQL gold, and what it cost: tokens (total and by
role), the largest single prompt (peak context), wall time, agents, model calls, missing shards. Results are Node 04
Trials (model = architecture), so report.compare gives paired differences."""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from agentlab.costs import Budget, BudgetExceeded
from agentlab.evals.graders import GradeResult
from agentlab.evals.runner import Trial, error_kind
from agentlab.multi.architectures import MultiResult, run_arch
from agentlab.multi.tasks import MultiTask, grade


def to_trial(task: MultiTask, r: MultiResult, conn, k: int = 0) -> Trial:
    ok, detail = grade(task, r.answer, conn) if r.answer is not None else (False, r.error or "no answer")
    if ok and r.missing_shards:
        # why: an answer that silently skipped shards is wrong even when it happens to match (TEXTBOOK §5)
        ok, detail = False, f"answered with shards missing: {r.missing_shards}"
    verdict = "pass" if ok else ("error" if r.answer is None else "fail")
    kind = None
    if not ok and r.provider_errors:
        # why: rate limits and outages are the provider's failure, not the architecture's; exclude them from
        # accuracy the same way for every architecture (single included)
        verdict, kind = "error", "provider"
    return Trial(task_id=task.id, trial=k, model=r.arch, verdict=verdict,
                 grades=[GradeResult("gold", "pass" if ok else "fail", detail[:500])],
                 replies=[json.dumps(r.answer, sort_keys=True, default=str)], tool_calls=[], transcript=[],
                 cost_usd=r.cost_usd, latency_s=r.latency_s, turns=len(r.calls), stops=[], error=r.error,
                 tags=[task.answer_kind], split="dev", error_kind=kind,
                 extra={"input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                        "peak_context": r.peak_context, "tokens_by_role": r.tokens_by_role(), "agents": r.agents,
                        "delegations": r.delegations, "missing_shards": r.missing_shards,
                        "conflicts": r.conflicts, "provider_errors": r.provider_errors})


def run_multi(tasks: list[MultiTask], archs: list[str], get_model: Callable, conn, *, trials: int = 1,
              budget: Budget | None = None, out_dir: Path | None = None, max_parallel: int = 6) -> list[Trial]:
    out: list[Trial] = []
    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "trials.jsonl").write_text("")
        (Path(out_dir) / "transcripts").mkdir(exist_ok=True)
    for k in range(trials):
        for task in tasks:
            for arch in archs:
                kind = "agent"
                spent0 = budget.spent_usd if budget else 0.0
                try:
                    r = run_arch(arch, task, get_model, conn, budget, max_parallel)
                except BudgetExceeded:
                    raise
                except Exception as e:  # noqa: BLE001
                    # why the budget delta: money spent before the crash is still money spent
                    r = MultiResult(arch, error=f"{type(e).__name__}: {e}",
                                    cost_usd=(budget.spent_usd - spent0) if budget else 0.0)
                    kind = error_kind(e)
                if budget is not None and budget.spent_usd > budget.limit_usd:
                    # why: workers stop quietly on budget (run_agent returns stop="budget"); a result produced
                    # while the money ran out is not a fair trial, and the run must not keep going
                    raise BudgetExceeded(f"budget exhausted during {arch} on {task.id}")
                tr = to_trial(task, r, conn, k)
                if tr.verdict == "error" and tr.error_kind is None:
                    tr.error_kind = kind
                out.append(tr)
                if out_dir:
                    with open(Path(out_dir) / "trials.jsonl", "a") as f:
                        f.write(json.dumps(asdict(tr), default=str) + "\n")
                    safe = arch.replace(":", "_").replace("@", "_")
                    (Path(out_dir) / "transcripts" / f"{task.id}__{safe}__{k}.json").write_text(
                        json.dumps(r.transcripts, default=str, indent=1))
    return out


def _group(ts: list[Trial]) -> dict[str, list[Trial]]:
    g: dict[str, list[Trial]] = defaultdict(list)
    for t in ts:
        g[t.task_id].append(t)
    return dict(g)


def summarize(trials: list[Trial]) -> dict[str, dict]:
    by: dict[str, list[Trial]] = defaultdict(list)
    for t in trials:
        if t.verdict == "error" and t.error_kind == "provider":
            continue
        by[t.model].append(t)
    out = {}
    mean = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    for arch, ts in by.items():
        lat = sorted(t.latency_s for t in ts)
        roles: dict[str, list[int]] = defaultdict(list)
        for t in ts:
            for role, n in t.extra.get("tokens_by_role", {}).items():
                roles[role].append(n)
        out[arch] = {
            "n": len(ts),
            "accuracy": mean([t.verdict == "pass" for t in ts]),
            "errors": sum(t.verdict == "error" for t in ts),
            "provider_errors": sum(1 for t in trials if t.model == arch and t.error_kind == "provider"),
            "tokens": mean([t.extra["input_tokens"] + t.extra["output_tokens"] for t in ts]),
            "peak_context": max((t.extra["peak_context"] for t in ts), default=0),
            "cost": mean([t.cost_usd for t in ts]),
            "p50_s": lat[len(lat) // 2] if lat else None,
            "agents": mean([t.extra["agents"] for t in ts]),
            "calls": mean([t.turns for t in ts]),
            "missing": sum(len(t.extra["missing_shards"]) > 0 for t in ts),
            "conflicts": sum(t.extra["conflicts"] for t in ts),
            "tokens_by_role": {r: sum(v) / len(ts) for r, v in roles.items()},
            "by_task": {tid: f"{sum(t.verdict == 'pass' for t in g)}/{len(g)}"
                        for tid, g in _group(ts).items()},
        }
    return out


def render(trials: list[Trial], baseline: str | None = None) -> str:
    s = summarize(trials)
    if not s:
        return "no trials\n"
    base = baseline if baseline in s else next(iter(s))
    f = lambda x, p=True: "–" if x is None else (f"{x:.0%}" if p else f"{x:,.0f}")  # noqa: E731
    rows = ["| architecture | accuracy | errors (+provider, excluded) | tokens/task | × tokens | peak prompt | $/task | p50 s | agents | "
            "calls | runs w/ missing shards | conflicts |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for a, v in s.items():
        ratio = v["tokens"] / s[base]["tokens"] if s[base]["tokens"] else None
        ratio_s = "–" if ratio is None else f"{ratio:.1f}×"
        p50 = "–" if v["p50_s"] is None else f"{v['p50_s']:.1f}"
        rows.append(f"| {a} | {f(v['accuracy'])} | {v['errors']} (+{v['provider_errors']}) | {f(v['tokens'], False)} | "
                    f"{ratio_s} | "
                    f"{v['peak_context']:,} | {v['cost'] or 0:.4f} | {p50} | {v['agents']:.1f} | "
                    f"{v['calls']:.1f} | {v['missing']} | {v['conflicts']} |")
    lines = ["\n".join(rows), "", f"(× tokens is relative to {base})", ""]
    tasks = sorted({tid for v in s.values() for tid in v["by_task"]})
    lines.append("| task (passes/trials) | " + " | ".join(s) + " |")
    lines.append("|---|" + "---|" * len(s))
    for tid in tasks:
        lines.append(f"| {tid} | " + " | ".join(v["by_task"].get(tid, "–") for v in s.values()) + " |")
    lines.append("")
    for a, v in s.items():
        if len(v["tokens_by_role"]) > 1:
            lines.append(f"- {a}: tokens by role: " + ", ".join(f"{r} {n:,.0f}" for r, n in
                                                                v["tokens_by_role"].items()))
    return "\n".join(lines) + "\n"
