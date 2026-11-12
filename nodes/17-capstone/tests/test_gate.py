"""AGENT-OFF: launch_decision (YOU_DO task 3)."""
import copy
import datetime as dt

import pytest

from agentlab.launch.gate import launch_decision

NOW = dt.datetime(2026, 11, 20, 12, 0, tzinfo=dt.timezone.utc)
FRESH = "2026-11-18T09:00:00+00:00"


def M(v, at=FRESH):
    return {"value": v, "measured_at": at, "source": "runs/x"}


def R(metric, op, th, sev="blocker", **kw):
    return {"metric": metric, "op": op, "threshold": th, "severity": sev, **kw}


def test_go_and_no_go():
    card = {"pass": M(0.9), "asr": M(0.02), "cost": M(0.7)}
    rules = [R("pass", ">=", 0.85), R("asr", "<=", 0.05), R("cost", "<=", 0.6, "warning")]
    before = copy.deepcopy((card, rules))
    d = launch_decision(card, rules, now=NOW)
    assert d.go and d.blockers == [] and len(d.passed) == 2
    assert d.warnings == ["cost = 0.7 (needs <= 0.6)"]
    assert (card, rules) == before
    d = launch_decision({**card, "pass": M(0.8)}, rules, now=NOW)
    assert not d.go and d.blockers[0].startswith("pass") and "0.8" in d.blockers[0]


def test_missing_and_optional():
    rules = [R("pass", ">=", 0.85), R("chaos", "<=", 0, optional=True), R("lat", "<=", 30, "warning")]
    d = launch_decision({"lat": M(None)}, rules, now=NOW)
    assert d.blockers == ["pass: not measured"] and set(d.warnings) == {"chaos: not measured", "lat: not measured"}


def test_stale_and_undatable_evidence():
    rules = [R("pass", ">=", 0.5, max_age_days=7), R("asr", "<=", 0.1)]
    d = launch_decision({"pass": M(0.9, "2026-11-01T00:00:00+00:00"), "asr": M(0.0, "yesterday")}, rules, now=NOW)
    assert not d.go and [b.split(":")[0] for b in d.blockers] == ["pass", "asr"]
    assert all("stale" in b for b in d.blockers)
    d = launch_decision({"asr": M(0.0, "2026-11-19T00:00:00")}, [R("asr", "<=", 0.1)], now=NOW)
    assert not d.go, "no timezone: can't be dated reliably"
    d = launch_decision({"pass": M(0.9, "2026-11-08T00:00:00+00:00")}, [R("pass", ">=", 0.5)], now=NOW)
    assert d.go, "default max age is 14 days"
    d = launch_decision({"pass": M(0.9, "2099-01-01T00:00:00+00:00")}, [R("pass", ">=", 0.5)], now=NOW)
    assert not d.go, "evidence from the future isn't evidence"
    d = launch_decision({"c": M(0, "2026-01-01T00:00:00+00:00")}, [R("c", "<=", 0, optional=True)], now=NOW)
    assert d.go and d.warnings[0].startswith("c: stale"), "optional + stale is a warning, like optional + missing"


def test_policy_typos_fail_loudly():
    for bad in ([R("x", ">", 1)], [R("x", ">=", 1, "info")], [{"metric": "x", "op": ">="}], []):
        with pytest.raises(ValueError):
            launch_decision({"x": M(5)}, bad, now=NOW)
