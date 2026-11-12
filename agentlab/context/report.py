"""What a context strategy costs and what it buys (TEXTBOOK §5): success vs tokens, per variant and length."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def summarize_context(trials) -> dict[str, dict]:
    """label -> {pass_rate, by_length, input_tokens_per_trial, cache_share, cost_per_trial, compactions_per_trial,
    max_call_est_tokens}. Trials with errors (provider, timeout) are left out of pass rates, as in Node 04."""
    by_label = defaultdict(list)
    for t in trials:
        by_label[t.model].append(t)
    out = {}
    for label, ts in by_label.items():
        stats = [s for t in ts for s in t.extra.get("turn_stats", [])]
        inp = sum(s["input_tokens"] for s in stats)
        lengths = defaultdict(list)
        for t in ts:
            for tag in t.tags:
                if tag.startswith("len") and t.verdict in ("pass", "fail"):
                    lengths[tag].append(t.verdict == "pass")
        out[label] = {
            "trials": len(ts),
            "pass_rate": _mean(t.verdict == "pass" for t in ts if t.verdict in ("pass", "fail")),
            "by_length": {k: _mean(v) for k, v in sorted(lengths.items(), key=lambda kv: int(kv[0][3:]))},
            "input_tokens_per_trial": inp / len(ts) if ts else 0,
            "cache_share": (sum(s["cache_read_tokens"] for s in stats) / inp) if inp else None,
            "cost_per_trial": _mean(t.cost_usd for t in ts),
            "compactions_per_trial": sum(s["action"] == "compacted" for s in stats) / len(ts) if ts else 0,
            "max_call_est_tokens": max((s["est_after"] or 0 for s in stats), default=0),
        }
    return out


def render_context_report(trials, title: str = "context") -> str:
    s = summarize_context(trials)
    pct = lambda x: "–" if x is None else f"{x:.0%}"  # noqa: E731
    lengths = sorted({k for v in s.values() for k in v["by_length"]}, key=lambda k: int(k[3:]))
    head = ["variant", "pass", *lengths, "input tok/trial", "cache share", "$/trial", "compactions", "max context"]
    rows = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for label, v in s.items():
        rows.append("| " + " | ".join([label, pct(v["pass_rate"]), *[pct(v["by_length"].get(k)) for k in lengths],
                                       f"{v['input_tokens_per_trial']:,.0f}", pct(v["cache_share"]),
                                       f"{v['cost_per_trial'] or 0:.4f}", f"{v['compactions_per_trial']:.1f}",
                                       f"{v['max_call_est_tokens']:,}"]) + " |")
    return f"# Context report: {title}\n\n" + "\n".join(rows) + "\n"


def write_tokens_by_turn(trials, path: Path) -> None:
    """One row per customer turn: the curve of TEXTBOOK §5 (input tokens vs turn, per variant)."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variant", "task", "trial", "session", "turn", "input_tokens", "cache_read_tokens", "action"])
        for t in trials:
            for st in t.extra.get("turn_stats", []):
                w.writerow([t.model, t.task_id, t.trial, st.get("session", 0), st["turn"], st["input_tokens"],
                            st["cache_read_tokens"], st["action"]])
