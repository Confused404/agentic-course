"""Same tasks, same model, three implementations (Node 16 TEXTBOOK §6): the course's own loop, Pydantic AI and
LangGraph, scored by the same Node 04 graders through run_trial's assistant_factory."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from agentlab.config import ROOT, resolve
from agentlab.costs import Budget, BudgetExceeded
from agentlab.evals.runner import Trial, run_trial
from agentlab.evals.task import Task

IMPLS = ("native", "pydantic-ai", "langgraph")
# the code each implementation needs on top of the shared tools/prompts (for the size comparison). Not like for like:
# the native support.py also carries Node 06's memory, notes and context strategies, which the ports leave out
SOURCES = {"native": ["agentlab/agent/loop.py", "agentlab/assistant/support.py"],
           "pydantic-ai": ["agentlab/frameworks/pydantic_port.py", "agentlab/frameworks/convert.py"],
           "langgraph": ["agentlab/frameworks/graph_port.py", "agentlab/frameworks/graph_nodes.py"]}


def factory_for(impl: str, alias: str, *, pai_model_factory: Callable | None = None):
    """An assistant_factory for run_trial, or None for the native SupportAssistant."""
    if impl == "native":
        return None
    if impl == "langgraph":
        from agentlab.frameworks.graph_port import GraphSupportAssistant
        return lambda model, conn, cid, budget: GraphSupportAssistant(model, conn, cid, budget)
    if impl == "pydantic-ai":
        from agentlab.frameworks.pydantic_port import PydanticSupportAssistant, pai_model
        provider, model_id = resolve(alias)
        make = pai_model_factory or (lambda: pai_model(alias))
        return lambda model, conn, cid, budget: PydanticSupportAssistant(make(), conn, cid, budget,
                                                                         price_model=model_id, provider=provider)
    raise ValueError(f"unknown implementation {impl!r}: choose from {', '.join(IMPLS)}")


def code_lines(paths: list[str]) -> int:
    """Non-blank, non-comment lines (docstrings count: they're part of what you maintain)."""
    n = 0
    for p in paths:
        f = ROOT / p
        if f.exists():
            n += sum(1 for line in f.read_text().splitlines() if line.strip() and not line.strip().startswith("#"))
    return n


def run_compare(tasks: list[Task], impls: list[str], *, model_factory: Callable, alias: str, template_db: Path,
                trials: int = 1, budget: Budget | None = None, judge_factory=None, sim_factory=None,
                out_dir: Path | None = None, pai_model_factory: Callable | None = None) -> list[Trial]:
    for i in impls:
        if i not in IMPLS:
            raise ValueError(f"unknown implementation {i!r}: choose from {', '.join(IMPLS)}")
    from agentlab.assistant.prompts import get_prompt
    opts = {"system_prompt": get_prompt("v2"), "tool_variant": "v2"}
    if out_dir:
        (out_dir / "trials.jsonl").write_text("")
    out = []
    for k in range(trials):
        for task in tasks:
            for impl in impls:
                t = run_trial(task, model_factory(), template_db=template_db, trial=k, model_label=impl, budget=budget,
                              judge_factory=judge_factory, sim_factory=sim_factory, assistant_opts=opts,
                              assistant_factory=factory_for(impl, alias, pai_model_factory=pai_model_factory))
                out.append(t)
                if out_dir:
                    with open(out_dir / "trials.jsonl", "a") as f:
                        f.write(json.dumps(asdict(t), default=str) + "\n")
                if t.error and "BudgetExceeded" in t.error:
                    raise BudgetExceeded(t.error)
    return out


def summarize(trials: list[Trial]) -> dict[str, dict]:
    by: dict[str, list[Trial]] = {}
    for t in trials:
        by.setdefault(t.model, []).append(t)
    out = {}
    for impl, ts in by.items():
        ok = [t for t in ts if t.error_kind not in ("provider", "timeout")]
        n = len(ok)
        tok = [sum(s.get("input_tokens", 0) for s in t.extra.get("turn_stats", [])) for t in ok]
        lat = sorted(t.latency_s for t in ok)
        out[impl] = {"n": n, "excluded": len(ts) - n,
                     "pass_rate": (sum(t.verdict == "pass" for t in ok) / n) if n else None,
                     "errors": sum(t.verdict == "error" for t in ok),
                     "cost_per_conversation": (sum(t.cost_usd for t in ok) / n) if n else None,
                     "calls_per_conversation": (sum(t.turns for t in ok) / n) if n else None,
                     "input_tokens_per_conversation": (sum(tok) / n) if n else None,
                     "p50_latency_s": lat[(len(lat) - 1) // 2] if lat else None,
                     "code_lines": code_lines(SOURCES.get(impl, []))}
    return out


def render(summary: dict[str, dict]) -> str:
    def f(x, fmt):
        return "–" if x is None else format(x, fmt)
    rows = ["| implementation | n | pass | errors | $/conversation | calls | input tok | p50 s | code lines |",
            "|---|---|---|---|---|---|---|---|---|"]
    for impl, s in summary.items():
        rows.append(f"| {impl} | {s['n']} | {f(s['pass_rate'], '.0%')} | {s['errors']} | "
                    f"{'–' if s['cost_per_conversation'] is None else '$' + format(s['cost_per_conversation'], '.4f')} | "
                    f"{f(s['calls_per_conversation'], '.1f')} | {f(s['input_tokens_per_conversation'], ',.0f')} | "
                    f"{f(s['p50_latency_s'], '.1f')} | {s['code_lines']} |")
    return "\n".join(rows) + ("\n\nSame tasks, same model, same tools and prompt; differences come from the "
                              "implementations (and from noise: see Node 04). Code lines include docstrings, and "
                              "the native assistant also carries Node 06's memory/notes/context features.\n")
