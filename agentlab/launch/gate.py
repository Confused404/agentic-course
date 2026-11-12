"""Go / no-go for a launch. AGENT-OFF: written by hand in Node 17 YOU_DO task 3.

Tests: nodes/17-capstone/tests/test_gate.py. Read TEXTBOOK §3 first. Standard library only.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

OPS = (">=", "<=")


@dataclass
class Decision:
    go: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)


def launch_decision(scorecard: dict[str, dict], rules: list[dict], *, now: dt.datetime) -> Decision:
    """scorecard: metric -> {"value": float | None, "measured_at": ISO-8601 str with timezone, "source": str}.
    rules: [{"metric", "op" (">=" | "<="), "threshold", "severity" ("blocker" | "warning"), "optional" (default
    False), "max_age_days" (default 14)}]. Contract (each line is tested):

    1. Validate first: an op not in OPS, a severity other than blocker/warning, or a missing metric/op/threshold
       key -> ValueError (a typo in the policy must not silently pass a launch).
    2. Per rule, in order, exactly one outcome, as a message that starts with the metric name:
       - metric absent from the scorecard, or its value is None: "not measured". Optional rules -> warnings;
         others -> the rule's severity list (blocker -> blockers, warning -> warnings).
       - measured_at older than max_age_days before `now`, more than a day in the FUTURE, without a timezone, or
         unparseable: "stale" -> like "not measured" (optional rules -> warnings; others -> the severity list).
       - the comparison fails: "<metric> = <value> (needs <op> <threshold>)" -> the rule's severity list.
       - otherwise -> passed.
    3. go = no blockers. A launch with no rules at all is not a decision: rules == [] -> ValueError.
    4. Never mutate the inputs.
    """
    raise NotImplementedError("AGENT-OFF: Node 17 YOU_DO task 3")
