"""Task loading and the code graders."""
from pathlib import Path

import pytest

from agentlab.evals.graders import TrialContext, grade, snapshot
from agentlab.evals.task import load_tasks, script_from_steps
from agentlab.llm.types import Message, TextBlock, ToolResultBlock, ToolUseBlock
from shopfront import services

SUITE = Path(__file__).resolve().parents[1] / "evals" / "support"


def test_load_suite_and_filters():
    tasks = load_tasks(SUITE)
    assert len(tasks) >= 30 and len({t.id for t in tasks}) == len(tasks)
    held = load_tasks(SUITE, split="heldout")
    assert 5 <= len(held) <= 9 and all(t.split == "heldout" for t in held)
    assert all("privacy" in t.tags for t in load_tasks(SUITE, tags=["privacy"]))
    sims = [t for t in tasks if t.user_sim]
    assert sims and all(not t.turns for t in sims)


def test_load_rejects_bad_tasks(tmp_path):
    (tmp_path / "x.yaml").write_text("- {id: a, customer_id: 1, turns: [hi], graders: [{type: nope}]}\n")
    with pytest.raises(ValueError, match="a"):
        load_tasks(tmp_path)
    (tmp_path / "x.yaml").write_text("- {id: a, customer_id: 1, graders: []}\n")
    with pytest.raises(ValueError):
        load_tasks(tmp_path)
    (tmp_path / "x.yaml").write_text("- {id: a, customer_id: 1, turns: [hi], graders: []}\n")
    with pytest.raises(ValueError, match="grader"):
        load_tasks(tmp_path)


def test_script_from_steps():
    s = script_from_steps([{"call": "lookup_order", "args": {"order_id": 1}}, {"calls": [["a", {}], ["b", {"x": 1}]]},
                           {"say": "hi"}])
    assert s[0].tool_calls[0].name == "lookup_order" and [c.name for c in s[1].tool_calls] == ["a", "b"]
    assert s[2].text == "hi"


def ctx(conn, before, calls=(), replies=("ok",)):
    msgs = [Message.user("hi")]
    for i, (name, inp) in enumerate(calls):
        msgs += [Message("assistant", [ToolUseBlock(f"t{i}", name, inp)]),
                 Message("user", [ToolResultBlock(f"t{i}", "{}")])]
    msgs.append(Message("assistant", [TextBlock(replies[-1])]))
    return TrialContext(conn, before, msgs, list(replies), 9001)


def test_state_graders_only_count_changes(conn):
    before = snapshot(conn)
    c = ctx(conn, before)
    assert grade({"type": "refund", "order_id": 4828, "status": "issued"}, c).verdict == "fail", "seeded refund ignored"
    assert grade({"type": "no_side_effects"}, c).verdict == "pass"
    services.issue_refund(conn, 4822, 2000, "not_as_described", actor="t")
    assert grade({"type": "refund", "order_id": 4822, "status": "issued", "amount_cents": 2000}, c).verdict == "pass"
    assert grade({"type": "refund", "order_id": 4822, "status": "issued", "amount_cents": 4899}, c).verdict == "fail"
    assert grade({"type": "refund", "order_id": 4822, "status": "issued", "reason": "damaged"}, c).verdict == "fail"
    r = grade({"type": "refund", "order_id": 4822, "status": "none"}, c)
    assert r.verdict == "fail" and r.detail
    assert grade({"type": "refund_reasons_only", "reasons": ["not_as_described"]}, c).verdict == "pass"
    assert grade({"type": "no_side_effects"}, c).verdict == "fail"
    assert grade({"type": "escalated", "expected": False}, c).verdict == "pass"
    services.escalate_to_human(conn, 9001, "Package lost somewhere.", 4824, "t")
    assert grade({"type": "escalated", "expected": True}, c).verdict == "pass"
    assert grade({"type": "order_status", "order_id": 4821, "status": "delivered"}, c).verdict == "pass"


def test_process_and_reply_graders(conn):
    c = ctx(conn, snapshot(conn), calls=[("lookup_order", {}), ("check_refund_eligibility", {}), ("issue_refund", {})],
            replies=("First reply mentions the 30-day window.", "Done, REFUNDED."))
    assert grade({"type": "tools_called", "tools": ["lookup_order", "issue_refund"]}, c).verdict == "pass"
    assert grade({"type": "tools_not_called", "tools": ["issue_refund"]}, c).verdict == "fail"
    assert grade({"type": "tool_order", "before": "check_refund_eligibility", "after": "issue_refund"}, c).verdict == "pass"
    assert grade({"type": "tool_order", "before": "issue_refund", "after": "lookup_order"}, c).verdict == "fail"
    assert grade({"type": "tool_order", "before": "x", "after": "cancel_order"}, c).verdict == "pass", "after never called"
    assert grade({"type": "max_tool_calls", "n": 2}, c).verdict == "fail"
    assert grade({"type": "reply_contains_any", "values": ["refunded"]}, c).verdict == "pass"
    assert grade({"type": "reply_contains_any", "values": ["30-day"]}, c).verdict == "fail", "final reply only by default"
    assert grade({"type": "reply_contains_any", "values": ["30-day"], "scope": "any"}, c).verdict == "pass"
    assert grade({"type": "reply_not_contains", "values": ["30-DAY"]}, c).verdict == "fail", "checks every reply"
    assert grade({"type": "reply_regex", "pattern": r"done,\s+refunded"}, c).verdict == "pass"
    assert grade({"type": "judge", "rubric": "x"}, c).verdict == "unknown"
    assert grade({"type": "tools_called_any", "tools": ["nope", "lookup_order"]}, c).verdict == "pass"
    assert grade({"type": "tools_called_any", "tools": ["nope"]}, c).verdict == "fail"
    assert grade({"type": "reply_not_regex", "pattern": r"done,\s+refunded"}, c).verdict == "fail"
    assert grade({"type": "reply_not_regex", "pattern": r"never said"}, c).verdict == "pass"


def test_reply_text_is_normalised(conn):
    c = ctx(conn, snapshot(conn), replies=("Gift cards aren\u2019t   refundable.",))
    assert grade({"type": "reply_contains_any", "values": ["aren't refundable"]}, c).verdict == "pass"
    assert grade({"type": "reply_regex", "pattern": r"aren'?t be|aren't refundable"}, c).verdict == "pass"
    with pytest.raises(ValueError):
        grade({"type": "vibes"}, c)
