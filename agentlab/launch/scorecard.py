"""The launch scorecard (Node 17 TEXTBOOK §3): the evidence from earlier nodes' runs, as metrics with dates.

Every metric is {"value", "measured_at" (ISO-8601, UTC), "source" (the run dir)}. measured_at comes from the run's
meta.json "started" field if it has a timezone, else the meta.json (or results file) modification time.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path


def measured_at(run_dir: Path) -> str:
    meta = run_dir / "meta.json"
    if meta.exists():
        try:
            started = json.loads(meta.read_text()).get("started")
            if started and dt.datetime.fromisoformat(started).tzinfo is not None:
                return started
        except ValueError:
            pass
        ref = meta
    else:
        ref = next((p for p in (run_dir / "trials.jsonl", run_dir / "results.jsonl") if p.exists()), run_dir)
    return dt.datetime.fromtimestamp(ref.stat().st_mtime, dt.timezone.utc).isoformat(timespec="seconds")


def _pick(summary: dict, key: str | None, what: str) -> dict:
    if not summary:
        raise ValueError(f"{what}: the run has no results")
    if key is None:
        if len(summary) > 1:
            raise ValueError(f"{what}: the run has several ({', '.join(summary)}); say which one")
        key = next(iter(summary))
    if key not in summary:
        raise ValueError(f"{what}: {key!r} not in the run ({', '.join(summary)})")
    return summary[key]


def build_scorecard(*, evals_dir=None, evals_model=None, perf_dir=None, perf_config=None, security_dir=None,
                    security_defense=None, chaos_dir=None, chaos_config="durable", human_cost_usd=4.0) -> dict:
    card: dict[str, dict] = {}

    def put(name, value, run_dir):
        card[name] = {"value": None if value is None else float(value), "measured_at": measured_at(Path(run_dir)),
                      "source": str(run_dir)}
    if evals_dir:
        from agentlab.evals.report import summarize
        from agentlab.evals.runner import load_trials
        trials = load_trials(Path(evals_dir) / "trials.jsonl")
        _pick(summarize(trials), evals_model, "evals")            # validates the model choice
        dev = [t for t in trials if t.split != "heldout" and (evals_model is None or t.model == evals_model)]
        s = next(iter(summarize(dev).values())) if dev else {}
        # why without held-out: a held-out task counted here too would be measured twice, and tuned-on tasks
        # would hide behind it
        put("regression_pass_rate", s.get("pass_rate"), evals_dir)
        put("pass_hat_3", s.get("pass_hat_k"), evals_dir)
        held = [t for t in trials if t.split == "heldout" and (evals_model is None or t.model == evals_model)]
        hs = summarize(held) if held else {}
        put("heldout_pass_rate", next(iter(hs.values()))["pass_rate"] if hs else None, evals_dir)
    if perf_dir:
        from agentlab.evals.runner import load_trials
        from agentlab.perf.bench import summarize as perf_summarize
        s = _pick(perf_summarize(load_trials(Path(perf_dir) / "trials.jsonl"), human_cost_usd=human_cost_usd),
                  perf_config, "perf")
        e = s.economics
        cpr = e["cost_per_resolution"]
        put("cost_per_resolution", None if cpr is None or cpr == float("inf") else cpr, perf_dir)
        put("blended_cost", e["blended_cost"], perf_dir)
        put("p95_latency_s", e["p95_latency_s"], perf_dir)
    if security_dir:
        from agentlab.evals.runner import load_trials
        from agentlab.security.evals import security_summary
        s = _pick(security_summary(load_trials(Path(security_dir) / "trials.jsonl")), security_defense, "security")
        put("attack_success_rate", s["asr"], security_dir)
        put("benign_utility", s["utility_benign"], security_dir)
    if chaos_dir:
        from agentlab.reliability.chaos import ChaosResult, summarize as chaos_summarize
        rows = [ChaosResult(**json.loads(x)) for x in (Path(chaos_dir) / "results.jsonl").read_text().splitlines()
                if x.strip()]
        s = _pick(chaos_summarize(rows), chaos_config, "chaos")
        put("chaos_completed", s["completed"], chaos_dir)
        put("refunded_without_answer", s["silent"], chaos_dir)
    return card
