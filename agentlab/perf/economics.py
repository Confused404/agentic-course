"""What a support conversation really costs. AGENT-OFF: written by hand in Node 15 YOU_DO task 3.

Tests: nodes/15-cost-latency/tests/test_economics.py. Read TEXTBOOK §1 and §5 first. Standard library only.
"""
from __future__ import annotations

import math  # noqa: F401 - you will need it
from dataclasses import dataclass


@dataclass
class Economics:
    n: int                              # conversations counted
    resolved: int                       # verdict "pass"
    resolution_rate: float | None
    cost_per_conversation: float | None     # mean model cost over ALL n (failures cost money too)
    cost_per_resolution: float | None       # total model cost / resolved; math.inf if resolved == 0 and n > 0
    blended_cost: float | None              # (total model cost + human_cost_usd x unresolved) / n
    p50_latency_s: float | None
    p95_latency_s: float | None
    excluded: int                       # infrastructure errors left out (see rule 1)


def percentile(xs: list[float], q: float) -> float | None:
    """Nearest-rank percentile: the smallest value with at least q% of the data at or below it.
    sorted(xs)[ceil(q/100 * n) - 1] (index 0 when that is < 0). Empty -> None. 0 < q <= 100, else ValueError."""
    raise NotImplementedError("AGENT-OFF: Node 15 YOU_DO task 3")


def unit_economics(trials: list, *, human_cost_usd: float, costs: list[float] | None = None) -> Economics:
    """Unit economics of a set of Node 04 Trials (anything with .verdict, .error_kind, .cost_usd, .latency_s).
    Contract (each line is tested):

    1. Trials whose error_kind is "provider" or "timeout" are infrastructure failures, not answers: leave them
       out of everything (count them in `excluded`). Every other trial counts, including error_kind "agent".
    2. `costs`, if given, replaces each trial's cost_usd (same order as `trials`, same length, else ValueError):
       that's how shadow prices or recomputed costs come in.
    3. resolved = trials with verdict "pass". resolution_rate = resolved / n.
    4. cost_per_conversation = total cost / n. cost_per_resolution = total cost / resolved (math.inf if resolved
       is 0). blended_cost = (total cost + human_cost_usd * (n - resolved)) / n: an unresolved conversation goes
       to a person, and that person costs money.
    5. p50/p95 over the counted trials' latency_s, with percentile() above.
    6. n == 0 -> every rate/cost/latency field None (and resolved 0).
    7. human_cost_usd < 0 -> ValueError.
    """
    raise NotImplementedError("AGENT-OFF: Node 15 YOU_DO task 3")
