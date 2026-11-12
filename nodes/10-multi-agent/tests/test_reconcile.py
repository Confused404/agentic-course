"""AGENT-OFF: reconcile (YOU_DO task 2). Work out each expected value on paper before running."""
import copy

from agentlab.multi.reconcile import Reconciled, WorkerReport, reconcile


def R(shard, items, notes="", ok=True):
    return WorkerReport(shard, items, notes, ok)


def test_clean_merge_sorted():
    r = reconcile(["b", "a"], [R("b", {"Z-2": 1, "B-1": 2}), R("a", {"A-9": 3})])
    assert isinstance(r, Reconciled)
    assert list(r.merged) == ["A-9", "B-1", "Z-2"] and r.merged["Z-2"] == 1
    assert (r.missing_shards, r.duplicates, r.conflicts, r.unexpected_shards) == ([], [], {}, [])


def test_missing_keeps_expected_order():
    r = reconcile(["c", "a", "b"], [R("a", {"x": 1}), R("b", {}, ok=False)])
    assert r.missing_shards == ["c", "b"]
    assert r.merged == {"x": 1}


def test_duplicates_and_conflicts():
    r = reconcile(["a", "b", "c"], [R("a", {"k1": {"v": 1}, "k2": 5}), R("b", {"k1": {"v": 1}, "k2": 6}),
                                    R("c", {"k2": 5})])
    assert r.duplicates == ["k1"] and r.merged["k1"] == {"v": 1}
    assert r.conflicts == {"k2": [5, 6]}, "distinct values, in the order first seen"
    assert "k2" not in r.merged, "a conflict is withheld, not resolved silently"


def test_unexpected_shard_is_not_evidence():
    r = reconcile(["a"], [R("a", {"x": 1}), R("zz", {"x": 2, "y": 3}), R("zz", {"y": 4})])
    assert r.unexpected_shards == ["zz"]
    assert r.merged == {"x": 1} and r.conflicts == {}


def test_last_report_per_shard_wins():
    r = reconcile(["a", "b"], [R("a", {}, ok=False), R("b", {"y": 1}), R("a", {"x": 1}), R("b", {}, ok=False)])
    assert r.merged == {"x": 1}, "a's retry replaced its failure; b's failure replaced its report"
    assert r.missing_shards == ["b"]


def test_notes_and_purity():
    reps = [R("a", {"x": [1, 2]}, notes="  partial: 2 products had no reviews "), R("b", {"y": 1}, notes="   ")]
    before = copy.deepcopy(reps)
    r = reconcile(["a", "b"], reps)
    assert r.notes == {"a": "partial: 2 products had no reviews"}
    assert reps == before, "never mutate the reports"
    assert r.merged is not reps[0].items


def test_mixed_key_types_sort_as_strings():
    r = reconcile(["a"], [R("a", {2: "b", 10: "a", "1": "c"})])
    assert list(r.merged) == ["1", 10, 2]


def test_empty():
    r = reconcile([], [])
    assert r.merged == {} and r.missing_shards == []


def test_failed_reports_contribute_nothing():
    r = reconcile(["a", "b"], [R("a", {"x": 1}, notes="half done", ok=False), R("b", {"y": 2}),
                               R("zz", {"q": 1}, notes="wandered")])
    assert r.merged == {"y": 2} and r.missing_shards == ["a"]
    assert r.notes == {}, "no notes from failed or unexpected reports"


def test_a_retry_replaces_an_ok_report_entirely():
    r = reconcile(["a"], [R("a", {"x": 1, "old": 0}), R("a", {"x": 2})])
    assert r.merged == {"x": 2}, "the first attempt's items are gone, not merged or conflicting"
    assert r.conflicts == {} and r.duplicates == []


def test_lists_are_sorted():
    r = reconcile(["c", "b", "a"], [R("c", {"k9": 1, "k2": 1, "z": 1, "m": 1}), R("b", {"k9": 1, "k2": 1, "z": 2, "m": 3}),
                                    R("y", {}), R("x", {}), R("a", {})])
    assert r.duplicates == ["k2", "k9"]
    assert list(r.conflicts) == ["m", "z"]
    assert r.unexpected_shards == ["x", "y"]


def test_conflict_order_follows_first_report_position():
    r = reconcile(["a", "b"], [R("a", {"k": 1}), R("b", {"k": 2}), R("a", {"k": 3})])
    assert r.conflicts == {"k": [3, 2]}, "a's retry keeps a's position (first in the list)"
