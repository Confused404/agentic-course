"""Evaluating triage methods (TEXTBOOK §6): accuracy (gold or acceptable secondary), macro-F1, priority, cost,
latency, which stage decided, and the selective-prediction curve. Results are Node 04 Trials (model = method), so
report.compare gives paired differences between methods."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from agentlab.costs import Budget, BudgetExceeded
from agentlab.evals.graders import GradeResult
from agentlab.evals.runner import Trial, error_kind
from agentlab.workflows import selective as selective_module
from agentlab.workflows.tickets import CATEGORIES, Ticket
from agentlab.workflows.triage import TriageResult, run_method


def to_trial(t: Ticket, method: str, r: TriageResult, k: int = 0) -> Trial:
    acceptable = r.category is not None and t.acceptable(r.category)
    # why: only a deliberate rules abstention is "no answer, no error"; anything else without a label (a crash in
    # your rules, unparseable output, a missing set_triage) is an error and must show up as one
    abstain = r.stage == "rules:abstain"
    verdict = "error" if r.category is None and not abstain else ("pass" if acceptable else "fail")
    tags = ["hard" if t.hard else "easy"] + (["ambiguous"] if t.ambiguous else [])
    return Trial(task_id=str(t.id), trial=k, model=method, verdict=verdict,
                 grades=[GradeResult("category", "pass" if acceptable else "fail", f"{r.category} vs {t.category}")],
                 replies=[json.dumps({"category": r.category, "priority": r.priority, "needs_human": r.needs_human})],
                 tool_calls=list(r.tool_calls), transcript=[], cost_usd=r.cost_usd, latency_s=r.latency_s,
                 turns=r.calls, stops=[], error=r.error, tags=tags, split=t.split,
                 extra={"pred": r.category, "gold": t.category, "strict": r.category == t.category,
                        "priority_ok": r.priority == t.priority, "confidence": r.confidence, "stage": r.stage,
                        "votes": r.votes, "abstained": r.category is None})


def run_triage(tickets: list[Ticket], methods: list[str], get_model: Callable, *, conn=None, trials: int = 1,
               budget: Budget | None = None, out_dir: Path | None = None) -> list[Trial]:
    out = []
    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "trials.jsonl").write_text("")     # why: a run owns its file; never append to an old one
    for k in range(trials):
        for t in tickets:
            for m in methods:
                kind = "agent"            # a failed parse or a missing set_triage is the method's fault
                try:
                    r = run_method(m, t, get_model, conn, budget)
                except BudgetExceeded:
                    raise
                except Exception as e:  # noqa: BLE001
                    r = TriageResult(None, None, stage=m, error=f"{type(e).__name__}: {e}")
                    kind = error_kind(e)
                tr = to_trial(t, m, r, k)
                if tr.verdict == "error":
                    tr.error_kind = kind
                out.append(tr)
                if out_dir:
                    with open(Path(out_dir) / "trials.jsonl", "a") as f:
                        f.write(json.dumps(asdict(tr), default=str) + "\n")
    return out


def macro_f1(pairs: list[tuple[str, str | None]]) -> float:
    """Strict macro-F1 over CATEGORIES (an abstention is a wrong answer for every class)."""
    f1s = []
    for c in CATEGORIES:
        tp = sum(1 for g, p in pairs if g == c and p == c)
        fp = sum(1 for g, p in pairs if g != c and p == c)
        fn = sum(1 for g, p in pairs if g == c and p != c)
        if tp + fp + fn == 0:
            continue
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return sum(f1s) / len(f1s) if f1s else 0.0


def _stage(t: Trial) -> str:
    if t.extra["stage"] == "rules:abstain":
        return "abstain"
    if t.verdict == "error":
        return "error"
    return t.extra["stage"].split(":")[0]


def summarize(trials: list[Trial]) -> dict[str, dict]:
    by = defaultdict(list)
    for t in trials:
        if t.verdict == "error" and t.error_kind == "provider":
            continue
        by[t.model].append(t)
    out = {}
    pct = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    for m, ts in by.items():
        answered = [t for t in ts if not t.extra["abstained"]]
        lat = sorted(t.latency_s for t in ts)
        curve = selective_module.coverage_curve([t.extra["confidence"] for t in answered],
                                                [t.verdict == "pass" for t in answered]) if answered else []
        out[m] = {
            "n": len(ts),
            "coverage": len(answered) / len(ts) if ts else 0.0,
            "accuracy": pct([t.verdict == "pass" for t in answered]),          # on what it answered
            "strict_accuracy": pct([t.extra["strict"] for t in answered]),     # gold label only, no secondaries
            "accuracy_easy": pct([t.verdict == "pass" for t in answered if "easy" in t.tags]),
            "accuracy_hard": pct([t.verdict == "pass" for t in answered if "hard" in t.tags]),
            "macro_f1": macro_f1([(t.extra["gold"], t.extra["pred"]) for t in ts]),
            "priority_acc": pct([t.extra["priority_ok"] for t in answered]),
            "cost_per_ticket": pct([t.cost_usd for t in ts]),
            "p50_s": lat[len(lat) // 2] if lat else None,
            "p95_s": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None,
            "stages": dict(Counter(_stage(t) for t in ts)),
            "abstained": sum(1 for t in ts if t.extra["abstained"]),
            "curve": curve,
            # mistakes only: abstentions and errors are counted (and fixed) separately
            "confusion": dict(Counter((t.extra["gold"], t.extra["pred"]) for t in ts
                                      if t.extra["pred"] is not None and t.verdict == "fail")),
        }
    return out


def render(trials: list[Trial], target_accuracy: float = 0.95) -> str:
    s = summarize(trials)
    f = lambda x, p=True: "–" if x is None else (f"{x:.0%}" if p else f"{x:.2f}")  # noqa: E731
    rows = ["| method | coverage | acc (answered) | strict | easy | hard | macro-F1 | priority | $/ticket | p50 s | "
            "p95 s | stages |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for m, v in s.items():
        rows.append(f"| {m} | {f(v['coverage'])} | {f(v['accuracy'])} | {f(v['strict_accuracy'])} | "
                    f"{f(v['accuracy_easy'])} | "
                    f"{f(v['accuracy_hard'])} | {v['macro_f1']:.2f} | {f(v['priority_acc'])} | "
                    f"{v['cost_per_ticket'] or 0:.5f} | {f(v['p50_s'], False)} | {f(v['p95_s'], False)} | "
                    f"{', '.join(f'{k}:{n}' for k, n in sorted(v['stages'].items()))} |")
    lines = ["\n".join(rows), ""]
    for m, v in s.items():
        if len({c for c, _, _ in v["curve"]}) > 1:
            th = selective_module.pick_threshold(v["curve"], target_accuracy)
            cov = next((c for t_, c, _ in v["curve"] if t_ == th), None)
            lines.append(f"- {m}: to reach {target_accuracy:.0%} accuracy, auto-handle confidence >= "
                         f"{th if th is not None else '(unreachable)'}"
                         + (f" ({cov:.0%} of answered tickets; the rest go to a human)" if cov else ""))
        worst = sorted(v["confusion"].items(), key=lambda kv: -kv[1])[:3]
        if worst:
            lines.append(f"- {m}: most common confusions (gold→pred): "
                         + ", ".join(f"{g}→{p} ×{n}" for (g, p), n in worst))
    return "\n".join(lines) + "\n"
