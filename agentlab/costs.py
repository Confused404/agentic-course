"""Cost accounting and hard spending caps.

Rule of the course: every live model call goes through a Budget. When the cap is hit, the
Budget raises BudgetExceeded and the run stops. An agent loop with no budget is a loop whose
cost is bounded only by your credit limit (Node 02 §6, Node 15).
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field

from agentlab.config import course_budget_usd, models_config
from agentlab.llm.types import Usage


class BudgetExceeded(RuntimeError):
    pass


def _price_table() -> dict:
    import agentlab.config as cfg
    table = dict(models_config().get("prices", {}))
    cache = cfg.RUNS / "openrouter_prices.json"      # written by `make models`; fresher than the TOML, so it wins
    if cache.exists():
        table.update(json.loads(cache.read_text()))
    return table


FREE = {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0}


def price_for(model: str) -> dict | None:
    table = _price_table()
    if model in table:
        return table[model]
    if model.endswith(":free"):                 # OpenRouter's free variants: $0 by definition (rate-limited instead)
        return FREE
    alias = models_config().get("price_aliases", {}).get(model)   # e.g. an OpenRouter id for a direct model
    return table.get(alias) if alias else None


def compute_cost(model: str, usage: Usage) -> float | None:
    """USD cost of one response. None if the model is unpriced (Budget then charges a conservative fallback)."""
    if usage.cost_usd is not None:              # provider told us exactly (e.g. OpenRouter)
        return usage.cost_usd
    p = price_for(model)
    if p is None:
        return None
    prefix = ""
    if "long_context_threshold" in p and usage.total_input > p["long_context_threshold"]:
        prefix = "long_"
    get = lambda k: p.get(prefix + k, p.get(k, 0.0))  # noqa: E731
    return (usage.input_tokens * get("input") + usage.output_tokens * get("output")
            + usage.cache_read_tokens * get("cache_read") + usage.cache_write_tokens * get("cache_write")) / 1e6


@dataclass
class Budget:
    """A hard cap shared by everything in one run. Thread-safe (parallel subagents share it)."""
    limit_usd: float = field(default_factory=course_budget_usd)
    label: str = "run"
    spent_usd: float = 0.0
    calls: int = 0
    unpriced_calls: int = 0
    allow_unpriced_free: bool = False   # True only for models you KNOW are free (local); default fails closed
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def charge(self, model: str, usage: Usage, provider: str | None = None) -> float:
        cost = compute_cost(model, usage)
        if cost is None and (provider == "ollama" or _provider_is_free(provider)):
            cost = 0.0   # local or self-hosted inference: your electricity or your GPU-hour, not a per-token invoice
        with self._lock:
            self.calls += 1
            if cost is None:
                # why: an unknown price must not mean "free". Charge at a deliberately expensive fallback
                # so a mis-typed model ID can't bypass the cap. Fix by adding a price or running `make models`.
                self.unpriced_calls += 1
                cost = 0.0 if self.allow_unpriced_free else _fallback_cost(usage)
            self.spent_usd += cost
            _ledger({"ts": time.time(), "label": self.label, "model": model, "cost_usd": cost,
                     "spent_usd": self.spent_usd, "usage": usage.__dict__})
            if self.spent_usd > self.limit_usd:
                raise BudgetExceeded(f"[{self.label}] spent ${self.spent_usd:.4f} > cap ${self.limit_usd:.2f}. "
                                     f"Raise the cap deliberately (BUDGET= / COURSE_BUDGET_USD) if intended.")
        return cost

    def check(self, estimate_usd: float = 0.0) -> None:
        """Call BEFORE an expensive step: raises if the cap is already reached or this step would cross it."""
        if self.spent_usd + estimate_usd > self.limit_usd:
            raise BudgetExceeded(f"[{self.label}] would exceed cap: spent ${self.spent_usd:.4f} + "
                                 f"est ${estimate_usd:.4f} > ${self.limit_usd:.2f}")

    @property
    def remaining_usd(self) -> float:
        return self.limit_usd - self.spent_usd


def _provider_is_free(provider: str | None) -> bool:
    """[providers.<name>] free = true in config/models.toml (e.g. your own self-hosted endpoint, elective E5)."""
    return bool(provider) and bool(models_config().get("providers", {}).get(provider, {}).get("free"))


def _fallback_cost(usage: Usage) -> float:
    p = models_config().get("prices", {}).get("default_unpriced", {"input": 10.0, "output": 50.0})
    return (usage.total_input * p["input"] + usage.output_tokens * p["output"]) / 1e6


def _ledger(entry: dict) -> None:
    import agentlab.config as cfg   # read at call time so tests can redirect RUNS
    cfg.RUNS.mkdir(parents=True, exist_ok=True)
    with open(cfg.RUNS / "costs.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")
