"""GIVEN: price token counts, including "shadow pricing" for free models (Node 15 TEXTBOOK §1).

On free models every call costs $0, which makes cost experiments meaningless. Shadow pricing answers "what would
this run have cost on model X?" from the token counts the free model actually used. It's an estimate (another
model would use a different number of tokens, and tokenizers differ), so reports label it.
"""
from __future__ import annotations

from agentlab.costs import price_for
from agentlab.llm.types import Usage


def usage_from(d: dict | None) -> Usage:
    if not d:
        return Usage()
    return Usage(**{k: d.get(k) for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
                                           "reasoning_tokens", "cost_usd") if k in d})


def list_price(usage: Usage, model: str) -> float | None:
    """What `usage` costs at `model`'s list prices (ignores any provider-reported cost). None if unpriced."""
    p = price_for(model)
    if p is None:
        return None
    prefix = "long_" if "long_context_threshold" in p and usage.total_input > p["long_context_threshold"] else ""
    get = lambda k: p.get(prefix + k, p.get(k, 0.0))  # noqa: E731
    return (usage.input_tokens * get("input") + usage.output_tokens * get("output")
            + usage.cache_read_tokens * get("cache_read") + usage.cache_write_tokens * get("cache_write")) / 1e6


def call_cost(record: dict, price_as: str | None = None) -> float:
    """Cost of one recorded call: shadow-priced at `price_as` if given, else the provider's reported cost, else list
    price for the model that answered, else 0.0 (unpriced: use is_priced() to flag it)."""
    u = usage_from(record.get("usage"))
    if price_as:
        return list_price(u, price_as) or 0.0
    if u.cost_usd is not None:
        return u.cost_usd
    return list_price(u, record.get("model", "")) or 0.0


def cache_read_share(usage: Usage) -> float | None:
    """Share of prompt tokens served from cache (None for a call with no prompt tokens)."""
    total = usage.total_input
    return usage.cache_read_tokens / total if total else None


def is_priced(record: dict, price_as: str | None = None) -> bool:
    """Does call_cost() know a real price for this record (rather than falling back to 0.0)?"""
    if not record.get("usage"):
        return True                     # a failed call: nothing to price
    if price_as:
        return price_for(price_as) is not None
    return usage_from(record.get("usage")).cost_usd is not None or price_for(record.get("model", "")) is not None
