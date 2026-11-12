"""The cost/latency bench (Node 15 TEXTBOOK §5): the same support tasks under several configurations, with quality
(Node 04 graders), unit economics, latency, cache behaviour and escalations side by side.

A configuration is a small spec string:   MODEL[+OPTION...]
  MODEL     an alias ("fast", "mid") or a cascade "CHEAP>STRONG" ("fast>mid")
  OPTION    cache:off|auto|explicit|timestamp   effort:low|medium|high   nosticky (cascade: escalate per call only)
e.g. "mid", "fast", "fast>mid", "mid+cache:auto", "fast>mid+cache:auto+effort:low"
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from agentlab.assistant.prompts import get_prompt
from agentlab.costs import Budget
from agentlab.evals.runner import Trial, run_trial
from agentlab.evals.task import Task
from agentlab.perf import economics as economics_module
from agentlab.perf.caching import POLICIES, CachePolicyModel, cache_summary
from agentlab.perf.pricing import call_cost, is_priced
from agentlab.perf.recorder import RecordingModel
from agentlab.perf.router import CascadeModel

EFFORTS = ("low", "medium", "high")


@dataclass(frozen=True)
class BenchConfig:
    spec: str
    cheap: str
    strong: str | None = None          # set for a cascade
    cache: str = "off"
    effort: str | None = None
    sticky: bool = True

    @property
    def aliases(self) -> list[str]:
        return [self.cheap] + ([self.strong] if self.strong else [])


def parse_config(spec: str) -> BenchConfig:
    parts = [p.strip() for p in spec.split("+")]
    model, opts = parts[0], parts[1:]
    if not model or any(c in model for c in ": ,"):
        raise ValueError(f"{spec!r}: the model part must be an alias or CHEAP>STRONG (aliases, not provider:model)")
    cheap, _, strong = model.partition(">")
    if ">" in model and (not cheap or not strong or ">" in strong):
        raise ValueError(f"{spec!r}: a cascade is CHEAP>STRONG")
    cache, effort, sticky = "off", None, True
    for o in opts:
        key, _, val = o.partition(":")
        if key == "cache" and val in POLICIES:
            cache = val
        elif key == "effort" and val in EFFORTS:
            effort = val
        elif o == "nosticky" and strong:
            sticky = False
        else:
            raise ValueError(f"{spec!r}: unknown option {o!r} (cache:{'|'.join(POLICIES)}, "
                             f"effort:{'|'.join(EFFORTS)}, nosticky for cascades)")
    return BenchConfig(spec, cheap, strong or None, cache, effort, sticky)


def build_model(cfg: BenchConfig, get_model: Callable, sink: list[dict], budget: Budget | None):
    """Leaves are recorded (so a discarded cheap answer is still counted), then laid out for caching."""
    def leaf(alias: str):
        return CachePolicyModel(RecordingModel(get_model(alias), sink, label=alias), cfg.cache)
    if cfg.strong is None:
        return leaf(cfg.cheap), None
    c = CascadeModel(leaf(cfg.cheap), leaf(cfg.strong), budget=budget, sticky=cfg.sticky)
    return c, c


def assistant_opts(cfg: BenchConfig) -> dict:
    return {"system_prompt": get_prompt("v2"), "tool_variant": "v2",
            "model_opts": {"effort": cfg.effort} if cfg.effort else {}}


def run_bench(tasks: list[Task], configs: list[str], *, template_db: Path, get_model: Callable, trials: int = 1,
              budget: Budget | None = None, judge_factory=None, sim_factory=None,
              price_as: dict[str, str] | None = None, out_dir: Path | None = None) -> list[Trial]:
    parsed = [parse_config(c) for c in configs]
    if len({c.spec for c in parsed}) != len(parsed):
        raise ValueError("duplicate configurations")
    if out_dir:
        (out_dir / "trials.jsonl").write_text("")
    out: list[Trial] = []
    for k in range(trials):
        for task in tasks:
            for cfg in parsed:                 # why interleaved: a slow minute hits every config, not just one
                sink: list[dict] = []
                model, cascade = build_model(cfg, get_model, sink, budget)
                t = run_trial(task, model, template_db=template_db, trial=k, model_label=cfg.spec, budget=budget,
                              judge_factory=judge_factory, sim_factory=sim_factory,
                              assistant_opts=assistant_opts(cfg))
                t.extra.update({
                    "calls": sink,
                    "recorded_cost": sum(call_cost(r) for r in sink),
                    "shadow_cost": (sum(call_cost(r, (price_as or {}).get(r.get("label"))) for r in sink)
                                    if price_as else None),
                    "price_as": dict(price_as) if price_as else None,
                    "escalations": cascade.escalations if cascade else 0,
                    "escalation_reasons": list(cascade.reasons) if cascade else [],
                })
                out.append(t)
                if out_dir:
                    with open(out_dir / "trials.jsonl", "a") as f:
                        f.write(json.dumps(asdict(t), default=str) + "\n")
    # note: when the budget runs out, run_trial raises BudgetExceeded and the trial that crossed the cap is lost
    # (its calls were paid for but never written); the CLI reports that spend separately
    return out


@dataclass
class ConfigSummary:
    config: str
    economics: dict
    shadow: bool
    calls_per_conversation: float
    prompt_tokens_per_conversation: float
    cache: dict
    escalation_rate: float | None          # escalations per conversation (cascades)
    escalation_reasons: dict = field(default_factory=dict)
    unpriced_calls: int = 0                # calls priced at $0 because no price was known
    call_latency_p50: float | None = None  # per model call, rate-limit waits excluded
    call_latency_p95: float | None = None
    wait_s_per_conversation: float = 0.0   # free-tier pacing waits (included in conversation latency)


def summarize(trials: list[Trial], *, human_cost_usd: float) -> dict[str, ConfigSummary]:
    by: dict[str, list[Trial]] = {}
    for t in trials:
        by.setdefault(t.model, []).append(t)
    out = {}
    for cfg, ts in by.items():
        shadow = all(t.extra.get("shadow_cost") is not None for t in ts)
        costs = [t.extra["shadow_cost"] if shadow else t.extra.get("recorded_cost", t.cost_usd) for t in ts]
        e = economics_module.unit_economics(ts, human_cost_usd=human_cost_usd, costs=costs)
        calls = [t.extra.get("calls", []) for t in ts]
        reasons: dict[str, int] = {}
        for t in ts:
            for r in t.extra.get("escalation_reasons", []):
                key = r.split(":")[0]
                reasons[key] = reasons.get(key, 0) + 1
        out[cfg] = ConfigSummary(
            cfg, asdict(e), shadow, sum(map(len, calls)) / len(ts),
            sum((r.get("usage") or {}).get("input_tokens", 0) + (r.get("usage") or {}).get("cache_read_tokens", 0)
                + (r.get("usage") or {}).get("cache_write_tokens", 0) for c in calls for r in c) / len(ts),
            cache_summary(calls),
            (sum(t.extra.get("escalations", 0) for t in ts) / len(ts)) if parse_config(cfg).strong else None,
            reasons)
        recs = [r for c in calls for r in c]
        out[cfg].unpriced_calls = sum(
            not is_priced(r, (t.extra.get("price_as") or {}).get(r.get("label")) if shadow else None)
            for t in ts for r in t.extra.get("calls", []))
        lat = [max(0.0, r.get("latency_s", 0.0) - r.get("wait_s", 0.0)) for r in recs if r.get("usage")]
        out[cfg].call_latency_p50 = economics_module.percentile(lat, 50) if lat else None
        out[cfg].call_latency_p95 = economics_module.percentile(lat, 95) if lat else None
        out[cfg].wait_s_per_conversation = sum(r.get("wait_s", 0.0) for r in recs) / len(ts)
    return out


def pareto(summaries: dict[str, ConfigSummary]) -> list[str]:
    """Configs no other config beats on both resolution rate and blended cost."""
    pts = {c: (s.economics["resolution_rate"] or 0.0, s.economics["blended_cost"] or 0.0)
           for c, s in summaries.items() if s.economics["n"]}

    def dominated(c: str) -> bool:
        q, k = pts[c]
        return any(q2 >= q and k2 <= k and (q2 > q or k2 < k) for o, (q2, k2) in pts.items() if o != c)
    return [c for c in pts if not dominated(c)]


def render(summaries: dict[str, ConfigSummary], *, human_cost_usd: float) -> str:
    def money(x):
        return "–" if x is None else ("∞" if x == float("inf") else f"${x:.4f}")

    def pct(x):
        return "–" if x is None else f"{x:.0%}"

    front = set(pareto(summaries))
    shadow = any(s.shadow for s in summaries.values())
    rows = ["| config | n | resolved | $/conversation | $/resolution | blended $ | p50 s | p95 s | calls | "
            "prompt tok | cache read | escalations | Pareto |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c, s in summaries.items():
        e = s.economics
        p50 = "–" if e["p50_latency_s"] is None else f"{e['p50_latency_s']:.1f}"
        p95 = "–" if e["p95_latency_s"] is None else f"{e['p95_latency_s']:.1f}"
        esc = "–" if s.escalation_rate is None else f"{s.escalation_rate:.2f}"
        rows.append(f"| {c} | {e['n']} | {pct(e['resolution_rate'])} | {money(e['cost_per_conversation'])} | "
                    f"{money(e['cost_per_resolution'])} | {money(e['blended_cost'])} | {p50} | {p95} | "
                    f"{s.calls_per_conversation:.1f} | {s.prompt_tokens_per_conversation:,.0f} | "
                    f"{pct(s.cache['read_share'])} | {esc} | {'★' if c in front else ''} |")
    notes = [f"\nblended $ = model cost + ${human_cost_usd:.2f} of human time per unresolved conversation.",
             "Per model call (rate-limit waits excluded): " + "; ".join(
                 f"{c} p50 {s.call_latency_p50:.1f}s p95 {s.call_latency_p95:.1f}s" for c, s in summaries.items()
                 if s.call_latency_p50 is not None)]
    waits = {c: s.wait_s_per_conversation for c, s in summaries.items() if s.wait_s_per_conversation > 0.5}
    if waits:
        notes.append("Free-tier pacing waited " + ", ".join(f"{c} {w:.0f}s" for c, w in waits.items()) +
                     " per conversation: conversation latencies include it and say little about the models.")
    unpriced = {c: s.unpriced_calls for c, s in summaries.items() if s.unpriced_calls}
    if unpriced:
        notes.append("UNPRICED calls counted as $0: " + ", ".join(f"{c} {n}" for c, n in unpriced.items()) +
                     " (add prices to config/models.toml or run `make models`).")
    if shadow:
        notes.append("Costs are SHADOW prices: the free models' token counts priced as the paid models you named "
                     "(an estimate: other models use other token counts).")
    return "\n".join(rows) + "\n" + "\n".join(notes) + "\n"
