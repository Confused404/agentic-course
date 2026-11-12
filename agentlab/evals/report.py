"""Turn trials into numbers with honest uncertainty (TEXTBOOK §4, §8). Statistics come from YOUR stats.py.

Headline = the TASK-level mean with a task bootstrap interval (trials of one task are correlated). The pooled
per-trial Wilson interval is shown too, labelled as ignoring clustering.
Excluded from graded trials (and counted separately): judge 'unknown', provider errors and timeouts.
"""
from __future__ import annotations

import math
from collections import defaultdict

from agentlab.evals.runner import Trial
from agentlab.evals.stats import bootstrap_mean_ci, paired_diff_ci, pass_at_k, pass_hat_k, wilson_interval


def _excluded(t: Trial) -> bool:
    return t.verdict == "unknown" or (t.verdict == "error" and t.error_kind in ("provider", "timeout"))


def per_task(trials: list[Trial]) -> dict[str, dict[str, tuple[int, int]]]:
    out: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for t in trials:
        if _excluded(t):
            continue
        cell = out[t.model][t.task_id]
        cell[1] += 1
        cell[0] += t.verdict == "pass"
    return {m: {k: (v[0], v[1]) for k, v in tasks.items()} for m, tasks in out.items()}


def _pct(vals: list[float | None], q: float) -> float | None:
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    s = sorted(vals)
    return s[max(1, math.ceil(q / 100 * len(s))) - 1]


def summarize(trials: list[Trial], k: int = 3) -> dict[str, dict]:
    pt = per_task(trials)
    out: dict[str, dict] = {}
    for model in dict.fromkeys(t.model for t in trials):
        ts = [t for t in trials if t.model == model]
        graded = [t for t in ts if not _excluded(t)]
        passes = sum(t.verdict == "pass" for t in ts)
        rates = [c / n for c, n in pt.get(model, {}).values() if n]
        mean, lo, hi = bootstrap_mean_ci(rates) if rates else (None, None, None)
        eligible = [(n, c) for c, n in pt.get(model, {}).values() if n >= k]
        hats = [pass_hat_k(n, c, k) for n, c in eligible]
        hat_mean, hat_lo, hat_hi = bootstrap_mean_ci(hats) if hats else (None, None, None)
        cost = sum(t.cost_usd for t in ts)
        lat = [t.latency_s for t in ts]
        tags: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for t in graded:
            for tag in t.tags:
                tags[tag][0] += t.verdict == "pass"
                tags[tag][1] += 1
        out[model] = {
            "trials": len(ts), "tasks": len({t.task_id for t in ts}), "passes": passes,
            "unknown": sum(t.verdict == "unknown" for t in ts), "errors": sum(t.verdict == "error" for t in ts),
            "provider_errors": sum(t.verdict == "error" and t.error_kind in ("provider", "timeout") for t in ts),
            "pass_rate": passes / len(graded) if graded else None, "wilson": wilson_interval(passes, len(graded)),
            # conservative: unknowns and every error count as failures
            "pass_rate_conservative": passes / len(ts) if ts else None,
            "task_mean": mean, "task_ci": (lo, hi),
            "pass_at_k": sum(pass_at_k(n, c, k) for n, c in eligible) / len(eligible) if eligible else None,
            "pass_hat_k": hat_mean, "pass_hat_k_ci": (hat_lo, hat_hi),
            "cost_per_trial": cost / len(ts) if ts else 0.0, "cost_per_pass": cost / passes if passes else None,
            "overhead_usd": sum(getattr(t, "overhead_usd", 0.0) for t in ts),
            "latency_p50": _pct(lat, 50), "latency_p90": _pct(lat, 90),
            "by_tag": {tag: p / n for tag, (p, n) in sorted(tags.items()) if n},
            "by_tag_counts": {tag: (p, n) for tag, (p, n) in sorted(tags.items())},
        }
    return out


def compare(trials: list[Trial], model_a: str, model_b: str) -> dict:
    pt = per_task(trials)
    for m in (model_a, model_b):
        if m not in pt:
            raise ValueError(f"model {m!r} not in these trials (have: {sorted(pt)})")
    rate = lambda m: {k: c / n for k, (c, n) in pt.get(m, {}).items() if n}  # noqa: E731
    a, b = rate(model_a), rate(model_b)
    diff, lo, hi = paired_diff_ci(a, b)
    return {"tasks": len(set(a) & set(b)), "diff": diff, "lo": lo, "hi": hi}


def pareto(summary: dict) -> list[str]:
    pts = {m: (s["task_mean"] or 0.0, s["cost_per_trial"]) for m, s in summary.items()}

    def dominated(m: str) -> bool:
        q, c = pts[m]
        return any((q2 >= q and c2 <= c) and (q2 > q or c2 < c) for o, (q2, c2) in pts.items() if o != m)
    return [m for m in pts if not dominated(m)]


def _f(x, pct: bool = True) -> str:
    if x is None:
        return "–"
    return f"{x * 100:.0f}%" if pct else f"${x:.4f}"


def render_markdown(trials: list[Trial], title: str = "Eval report", k: int = 3) -> str:
    s = summarize(trials, k)
    pt = per_task(trials)
    L = [f"# {title}", "", f"{len(trials)} trials · k = {k} · 95% intervals · headline = task mean with a bootstrap "
         f"over tasks (the per-trial Wilson interval ignores that trials of a task are correlated)", "",
         f"| model | **task mean [CI]** | pass^{k} [CI] | pass@{k} | per-trial rate [Wilson] | conservative | unknown | "
         f"errors (provider) | $/trial | $/pass | p50 s |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for m, r in s.items():
        lo, hi = r["wilson"]
        tlo, thi = r["task_ci"]
        hlo, hhi = r["pass_hat_k_ci"]
        p50 = f"{r['latency_p50']:.1f}" if r["latency_p50"] is not None else "–"
        L.append(f"| {m} | **{_f(r['task_mean'])}** [{_f(tlo)}–{_f(thi)}] | {_f(r['pass_hat_k'])} [{_f(hlo)}–{_f(hhi)}] | "
                 f"{_f(r['pass_at_k'])} | {_f(r['pass_rate'])} [{_f(lo)}–{_f(hi)}] | {_f(r['pass_rate_conservative'])} | "
                 f"{r['unknown']} | {r['errors']} ({r['provider_errors']}) | {_f(r['cost_per_trial'], False)} | "
                 f"{_f(r['cost_per_pass'], False)} | {p50} |")
    overhead = sum(r["overhead_usd"] for r in s.values())
    L += ["", f"**Pareto set** (task mean vs $/trial): {', '.join(pareto(s))} · judge + simulator spend: ${overhead:.4f}",
          "", "## Per task (passes / graded trials)", "", "| task | " + " | ".join(s) + " |", "|---|" + "---|" * len(s)]
    for task in sorted({t.task_id for t in trials}):
        cells = [f"{pt.get(m, {}).get(task, (0, 0))[0]}/{pt.get(m, {}).get(task, (0, 0))[1]}" for m in s]
        L.append(f"| {task} | " + " | ".join(cells) + " |")
    tags = sorted({tag for r in s.values() for tag in r["by_tag_counts"]})
    L += ["", "## By tag (exploratory: many small slices; don't draw conclusions without a planned comparison)", "",
          "| tag | " + " | ".join(s) + " |", "|---|" + "---|" * len(s)]
    for tag in tags:
        L.append(f"| {tag} | " + " | ".join(
            "{}/{}".format(*s[m]["by_tag_counts"][tag]) if tag in s[m]["by_tag_counts"] else "–" for m in s) + " |")
    L += ["", "## Failures to read (one per task × model)", ""]
    seen, bad = set(), []
    for t in trials:
        if t.verdict in ("fail", "unknown", "error") and (t.task_id, t.model) not in seen:
            seen.add((t.task_id, t.model))
            bad.append(t)
    for t in bad[:15]:
        why = "; ".join(f"{g.grader}: {g.detail[:160]}" for g in t.grades if g.verdict != "pass") or (t.error or "")
        kind = f" ({t.error_kind})" if t.error_kind else ""
        L.append(f"- **{t.task_id}** / {t.model} / trial {t.trial}: {t.verdict}{kind}: {why}")
    if not bad:
        L.append("- (none: read a few passes instead, graders have bugs too)")
    return "\n".join(L) + "\n"
