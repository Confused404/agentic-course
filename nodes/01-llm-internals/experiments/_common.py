"""Shared plumbing for Node 01 experiments (given; not part of the ticket)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from contextlib import contextmanager  # noqa: E402

from agentlab import tracing  # noqa: E402
from agentlab.config import RUNS, api_key, models_config, resolve  # noqa: E402
from agentlab.costs import Budget  # noqa: E402

OUT = RUNS / "node01"


@contextmanager
def run_span(name: str):
    """One trace per experiment run, so `make trace` shows every call of the run as one tree."""
    with tracing.agent_span(name):
        yield


def out_path(name: str, fresh: bool) -> Path:
    """Results append by default (so re-running one model keeps the others). --fresh starts over."""
    p = OUT / name
    if fresh:
        p.unlink(missing_ok=True)
    return p


def quick(provider: str) -> dict:
    """Request kwargs that keep reasoning short, for experiments that need a short direct answer.
    Why: reasoning tokens count toward max_tokens; a 'reply with 4 digits' probe can spend its whole
    budget thinking and return nothing, which would look like a recall failure (TEXTBOOK §6)."""
    if provider == "anthropic":
        return {"output_config": {"effort": "low"}}
    if provider == "openrouter":
        return {"extra_body": {"reasoning": {"effort": "low"}}}
    return {}   # Ollama: thinking models may still think; generous max_tokens covers it


def parse_args(default_models: str, default_budget: float, extra: list[tuple] = ()) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=default_models, help="comma-separated aliases from config/models.toml")
    ap.add_argument("--budget", type=float, default=default_budget, help="hard cap in USD for this run")
    ap.add_argument("--trials", type=int, default=None)
    ap.add_argument("--fresh", action="store_true", help="delete previous results for this experiment first")
    for args, kw in extra:
        ap.add_argument(*args, **kw)
    return ap.parse_args()


def targets(models_csv: str) -> list[tuple[str, str, str]]:
    """[(alias, provider, model)] for aliases whose provider has credentials; prints skips."""
    out = []
    for alias in [m.strip() for m in models_csv.split(",") if m.strip()]:
        provider, model = resolve(alias)
        if not api_key(provider):
            print(f"skip {alias}: no API key for {provider}")
            continue
        out.append((alias, provider, model))
    return out


def call(provider: str, model: str, *, system: str, user: str, budget: Budget, experiment: str,
         label: str = "", tools_anthropic=None, tools_openai=None, **kw):
    """Dispatch to the right raw caller with a single-turn conversation.

    Free OpenRouter models (the default without an Anthropic key) get the same treatment the course's model registry
    gives them from Node 02 on: calls are paced to stay under the free tier's per-minute limit, and OpenRouter's
    fallback list is sent, so one busy free model doesn't fill your tables with 429 errors."""
    from agentlab.probe import anthropic_call, openai_compat_call
    if provider == "openrouter":
        from agentlab.config import fallbacks_for, is_free_model
        if is_free_model(provider, model):
            import time
            from agentlab.llm import pacing
            rpm = models_config().get("free_tier", {}).get("requests_per_minute", 18)
            pacing._wait_for_slot(rpm, time.monotonic, time.sleep)
        fb = fallbacks_for(model)
        if fb:
            kw["extra_body"] = {**kw.get("extra_body", {}), "models": [model, *fb]}
    if provider == "anthropic":
        return anthropic_call(model, system=system, messages=[{"role": "user", "content": user}],
                              tools=tools_anthropic, budget=budget, experiment=experiment, label=label, **kw)
    return openai_compat_call(provider, model, system=system, messages=[{"role": "user", "content": user}],
                              tools=tools_openai, budget=budget, experiment=experiment, label=label, **kw)


# Shopfront-flavoured tools, written once in a neutral form and converted to each vendor's shape.
NEUTRAL_TOOLS = [
    {"name": "lookup_order", "description": "Get an order's status, items, dates and refunds by order id.",
     "schema": {"type": "object", "properties": {"order_id": {"type": "integer"}}, "required": ["order_id"]}},
    {"name": "refund_eligibility",
     "description": "Check whether an order can be refunded for a reason. No side effects.",
     "schema": {"type": "object", "properties": {
         "order_id": {"type": "integer"},
         "reason": {"type": "string", "enum": ["damaged", "not_as_described", "changed_mind", "late_delivery", "other"]}},
         "required": ["order_id", "reason"]}},
    {"name": "escalate_to_human", "description": "Hand the conversation to a human agent with a summary.",
     "schema": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}},
]


def tools_for_anthropic() -> list[dict]:
    return [{"name": t["name"], "description": t["description"], "input_schema": t["schema"]} for t in NEUTRAL_TOOLS]


def tools_for_openai() -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                              "parameters": t["schema"]}} for t in NEUTRAL_TOOLS]


def matrix_default() -> str:
    return ",".join(models_config()["matrix"]["default"])
