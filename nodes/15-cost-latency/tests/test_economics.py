"""AGENT-OFF: percentile, unit_economics (YOU_DO task 3)."""
import math
from types import SimpleNamespace as NS

import pytest

from agentlab.perf.economics import percentile, unit_economics


def T(verdict="pass", cost=0.01, lat=1.0, kind=None):
    return NS(verdict=verdict, cost_usd=cost, latency_s=lat, error_kind=kind)


def test_percentile_nearest_rank():
    xs = [5, 1, 3, 2, 4]
    assert percentile(xs, 50) == 3 and percentile(xs, 100) == 5 and percentile(xs, 1) == 1
    assert percentile(list(range(1, 101)), 95) == 95 and percentile([7.0], 95) == 7.0
    assert percentile([], 50) is None
    for q in (0, -1, 101):
        with pytest.raises(ValueError):
            percentile(xs, q)


def test_failures_cost_money_and_people():
    ts = [T("pass", 0.02), T("pass", 0.02), T("fail", 0.04), T("fail", 0.04, kind="agent")]
    e = unit_economics(ts, human_cost_usd=2.0)
    assert (e.n, e.resolved, e.excluded) == (4, 2, 0) and e.resolution_rate == 0.5
    assert e.cost_per_conversation == pytest.approx(0.03)
    assert e.cost_per_resolution == pytest.approx(0.06)
    assert e.blended_cost == pytest.approx((0.12 + 2 * 2.0) / 4)


def test_infrastructure_errors_are_excluded():
    ts = [T("pass", 0.01, 1.0), T("error", 0.5, 99.0, kind="provider"), T("error", 0.0, 600, kind="timeout")]
    e = unit_economics(ts, human_cost_usd=1.0)
    assert (e.n, e.excluded, e.resolved) == (1, 2, 1) and e.p95_latency_s == 1.0
    assert e.cost_per_conversation == pytest.approx(0.01)


def test_agent_crashes_count_as_unresolved():
    ts = [T("pass", 0.01), T("error", 0.02, kind="agent"), T("error", 0.0, kind="provider")]
    e = unit_economics(ts, human_cost_usd=1.0)
    assert (e.n, e.resolved, e.excluded) == (2, 1, 1), "exclude by error_kind, not by verdict"
    assert e.blended_cost == pytest.approx((0.03 + 1.0) / 2)


def test_costs_stay_aligned_when_trials_are_excluded():
    ts = [T("pass", 0.0, 1.0), T("error", 0.0, 9.0, kind="timeout"), T("fail", 0.0, 2.0)]
    e = unit_economics(ts, human_cost_usd=0.0, costs=[0.1, 5.0, 0.3])
    assert e.cost_per_conversation == pytest.approx(0.2), "the excluded trial's cost goes with it"


def test_shadow_costs_and_latency():
    ts = [T("pass", 0.0, 1.0), T("fail", 0.0, 3.0), T("pass", 0.0, 2.0)]
    e = unit_economics(ts, human_cost_usd=0.0, costs=[0.1, 0.2, 0.3])
    assert e.cost_per_resolution == pytest.approx(0.3) and e.p50_latency_s == 2.0 and e.p95_latency_s == 3.0
    with pytest.raises(ValueError):
        unit_economics(ts, human_cost_usd=0.0, costs=[0.1])


def test_edge_cases():
    e = unit_economics([T("fail", 0.1)], human_cost_usd=1.0)
    assert e.cost_per_resolution == math.inf and e.resolution_rate == 0.0
    e = unit_economics([], human_cost_usd=1.0)
    assert e.n == 0 and e.resolved == 0 and e.cost_per_conversation is None and e.p50_latency_s is None
    with pytest.raises(ValueError):
        unit_economics([T()], human_cost_usd=-1)
