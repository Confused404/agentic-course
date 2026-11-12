"""AGENT-OFF: next_feature, validate_update, record_attempt, stalled (YOU_DO task 2)."""
from dataclasses import replace

import pytest

from agentlab.harness.progress import MAX_NOTES, Feature, next_feature, record_attempt, stalled, validate_update

FEATS = [Feature("F1", "one", "passing", 1), Feature("F2", "two", "failing", 2), Feature("F3", "three"),
         Feature("F4", "four")]


def test_next_feature_in_order_with_attempt_limit():
    assert next_feature(FEATS, max_attempts=3).id == "F2"
    assert next_feature(FEATS, max_attempts=2).id == "F3", "F2 is out of attempts: move on"
    assert next_feature([Feature("F1", "x", "in_progress", 0), Feature("F2", "y")]).id == "F1"
    assert next_feature([replace(f, status="passing") for f in FEATS]) is None
    assert next_feature([]) is None


def test_validate_update_ids():
    p = validate_update(FEATS, FEATS[:3])
    assert len(p) == 1 and "ids" in p[0]
    assert len(validate_update(FEATS, [FEATS[1], FEATS[0], *FEATS[2:]])) == 1


def test_validate_update_fields():
    after = [replace(FEATS[0], title="ONE"), replace(FEATS[1], attempts=0), replace(FEATS[2], status="done"),
             replace(FEATS[3], notes="x" * (MAX_NOTES + 1))]
    p = validate_update(FEATS, after)
    assert [x.split(":")[0] for x in p] == ["F1", "F2", "F3", "F4"]
    assert "title" in p[0] and "attempts" in p[1] and "status" in p[2] and "notes" in p[3]


def test_validate_update_status_transitions():
    ok = [FEATS[0], replace(FEATS[1], status="in_progress"), replace(FEATS[2], status="in_progress"), FEATS[3]]
    assert validate_update(FEATS, ok) == []
    to_pass = [FEATS[0], FEATS[1], replace(FEATS[2], status="passing"), FEATS[3]]
    assert validate_update(FEATS, to_pass, allow_passing=True) == []
    p = validate_update(FEATS, to_pass)
    assert len(p) == 1 and p[0].startswith("F3") and "passing" in p[0]
    for bad in ([replace(FEATS[0], status="todo"), *FEATS[1:]],                  # passing -> todo
                [*FEATS[:2], replace(FEATS[2], status="failing"), FEATS[3]],    # only the harness fails a feature
                [FEATS[0], replace(FEATS[1], status="todo"), *FEATS[2:]]):      # failing -> todo
        assert len(validate_update(FEATS, bad)) == 1, bad
    back = [replace(FEATS[0], status="in_progress"), *FEATS[1:]]
    assert len(validate_update(FEATS, back)) == 1, "passing -> in_progress is not allowed"
    ip = [FEATS[0], FEATS[1], replace(FEATS[2], status="in_progress"), FEATS[3]]
    assert len(validate_update(ip, FEATS)) == 1, "in_progress -> todo is not allowed"


def test_validate_update_notes():
    assert len(validate_update(FEATS, [*FEATS[:3], replace(FEATS[3], notes=None)])) == 1
    assert validate_update(FEATS, [*FEATS[:3], replace(FEATS[3], notes="n" * MAX_NOTES)]) == []


def test_validate_update_order_of_problems():
    after = [replace(FEATS[0], title="X", attempts=9), *FEATS[1:]]
    p = validate_update(FEATS, after)
    assert len(p) == 2 and "title" in p[0] and "attempts" in p[1]


def test_record_attempt_is_pure():
    before = list(FEATS)
    out = record_attempt(FEATS, "F3", False, "y" * (MAX_NOTES + 50))
    assert FEATS == before and out is not FEATS
    f3 = out[2]
    assert (f3.status, f3.attempts, len(f3.notes)) == ("failing", 1, MAX_NOTES)
    assert out[0] is FEATS[0] or out[0] == FEATS[0]
    f2 = record_attempt(FEATS, "F2", True)[1]
    assert (f2.status, f2.attempts, f2.notes) == ("passing", 3, "")
    with pytest.raises(KeyError):
        record_attempt(FEATS, "F9", True)


def test_stalled():
    assert not stalled([1, 1, 1])
    assert stalled([1, 1, 1, 1])
    assert not stalled([0, 1, 1, 1])
    assert stalled([2, 3, 3, 3, 3], window=3)
    assert not stalled([2, 3, 3, 3, 4], window=3)
    assert stalled([3, 2, 2, 2], window=3), "going backwards is not progress"
