"""AGENT-OFF: coverage_curve and pick_threshold (YOU_DO task 4)."""
import pytest

from agentlab.workflows.selective import coverage_curve, pick_threshold


def test_curve():
    c = coverage_curve([0.9, 0.9, 0.6, 0.4], [True, True, False, True])
    assert c == [(0.9, 0.5, 1.0), (0.6, 0.75, pytest.approx(2 / 3)), (0.4, 1.0, 0.75)]
    assert coverage_curve([], []) == []
    unsorted = coverage_curve([0.4, 0.9, 0.6, 0.9], [True, True, False, True])
    assert unsorted == c, "input order must not matter: sort by confidence, don't scan in the order given"
    with pytest.raises(ValueError):
        coverage_curve([0.1], [])


def test_pick_threshold():
    c = coverage_curve([1.0, 1.0, 0.8, 0.8, 0.6, 0.6], [True, True, True, True, False, True])
    assert pick_threshold(c, 0.9) == 0.8, "lowest threshold that still meets the bar"
    assert pick_threshold(c, 0.8) == 0.6
    assert pick_threshold(coverage_curve([0.5], [False]), 0.5) is None
    assert pick_threshold([], 0.9) is None
    bumpy = [(1.0, 0.2, 1.0), (0.8, 0.5, 0.6), (0.6, 1.0, 0.95)]      # accuracy need not fall monotonically
    assert pick_threshold(bumpy, 0.9) == 0.6, "the LOWEST threshold meeting the bar, not the first failure"
