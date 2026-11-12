"""Go / no-go for a launch. AGENT-OFF (reference solution): written by hand in Node 17 YOU_DO task 3.

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
    if not rules:
        raise ValueError("no rules: a launch decision needs a policy")
    for r in rules:
        missing = [k for k in ("metric", "op", "threshold") if k not in r]
        if missing:
            raise ValueError(f"rule {r!r} is missing {missing}")
        if r["op"] not in OPS:
            raise ValueError(f"rule for {r['metric']}: op {r['op']!r} not in {OPS}")
        if r.get("severity", "blocker") not in ("blocker", "warning"):
            raise ValueError(f"rule for {r['metric']}: severity must be blocker or warning")
    d = Decision(go=False)
    for r in rules:
        name, sev = r["metric"], r.get("severity", "blocker")
        target = d.blockers if sev == "blocker" else d.warnings
        entry = scorecard.get(name)
        value = None if entry is None else entry.get("value")
        if value is None:
            (d.warnings if r.get("optional", False) else target).append(f"{name}: not measured")
            continue
        try:
            when = dt.datetime.fromisoformat(entry.get("measured_at", ""))
            if when.tzinfo is None:
                raise ValueError("no timezone")
            stale = now - when > dt.timedelta(days=r.get("max_age_days", 14)) or when > now + dt.timedelta(days=1)
        except (TypeError, ValueError):
            stale = True                 # why: evidence you can't date (or dated in the future) can't be trusted
        if stale:
            # optional rules: stale like missing is a warning (else deleting an old run would be the way to pass)
            (d.warnings if r.get("optional", False) else target).append(
                f"{name}: stale (measured {entry.get('measured_at')!r})")
            continue
        ok = value >= r["threshold"] if r["op"] == ">=" else value <= r["threshold"]
        if ok:
            d.passed.append(f"{name} = {value:g}")
        else:
            target.append(f"{name} = {value:g} (needs {r['op']} {r['threshold']:g})")
    d.go = not d.blockers
    return d
