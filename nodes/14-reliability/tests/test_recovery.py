"""AGENT-OFF: plan_recovery (YOU_DO task 3). Each journal below is a crash at a different moment."""
import pytest

from agentlab.llm.types import Message, TextBlock, ToolUseBlock, to_dict
from agentlab.reliability.recovery import plan_recovery

SIDE = {"issue_refund"}


def asst(*calls, text="", stop=None):
    blocks = ([TextBlock(text)] if text else []) + [ToolUseBlock(cid, name, args) for cid, name, args in calls]
    e = {"kind": "assistant", "message": to_dict(Message("assistant", blocks))}
    if stop is not None:
        e["stop_reason"] = stop
    return e


def J(*entries):
    start = {"kind": "start", "system": "sys", "messages": [to_dict(Message.user("refund 4822"))],
             "config": {"max_turns": 5}}
    return [{"seq": i + 1, **e} for i, e in enumerate([start, *entries])]


def R(cid, content="ok", is_error=False, **kw):
    return {"kind": "result", "call_id": cid, "content": content, "is_error": is_error, **kw}


ELIG = ("c1", "check_refund_eligibility", {"order_id": 4822})
REFUND = ("c2", "issue_refund", {"order_id": 4822, "amount_cents": 4899})


def test_needs_a_start():
    with pytest.raises(ValueError):
        plan_recovery([{"seq": 1, "kind": "assistant", "message": {}}], SIDE)


def test_crash_before_the_first_model_call():
    p = plan_recovery(J(), SIDE)
    assert p.status == "resume" and [m.role for m in p.messages] == ["user"] and not p.pending
    assert p.system == "sys" and p.config == {"max_turns": 5}


def test_completed_turns_are_rebuilt():
    p = plan_recovery(J(asst(ELIG), {"kind": "intent", "call_id": "c1", "tool": ELIG[1], "args": ELIG[2]},
                        R("c1", '{"eligible": true}')), SIDE)
    assert [m.role for m in p.messages] == ["user", "assistant", "user"]
    assert p.messages[2].content[0].tool_use_id == "c1" and not p.pending and p.status == "resume"


def test_read_tool_after_intent_is_simply_rerun():
    p = plan_recovery(J(asst(ELIG), {"kind": "intent", "call_id": "c1", "tool": ELIG[1], "args": ELIG[2]}), SIDE)
    assert [(c.call_id, c.action) for c in p.pending] == [("c1", "execute")]
    assert p.messages[-1].role == "assistant", "the open turn's results aren't appended yet"


def test_side_effect_after_intent_must_be_reconciled():
    p = plan_recovery(J(asst(ELIG), R("c1"), asst(REFUND),
                        {"kind": "intent", "call_id": "c2", "tool": "issue_refund", "args": REFUND[2]}), SIDE)
    assert [(c.call_id, c.tool, c.action) for c in p.pending] == [("c2", "issue_refund", "reconcile")]
    assert p.pending[0].args == REFUND[2]


def test_side_effect_without_intent_is_safe_to_execute():
    p = plan_recovery(J(asst(ELIG), R("c1"), asst(REFUND)), SIDE)
    assert [c.action for c in p.pending] == ["execute"]


def test_partial_turn_keeps_known_results_in_order():
    a = ("a", "lookup_order", {"order_id": 1})
    b = ("b", "issue_refund", {"order_id": 1})
    c = ("c", "lookup_order", {"order_id": 2})
    p = plan_recovery(J(asst(a, b, c), R("c", "C"), R("a", "A"),
                        {"kind": "intent", "call_id": "b", "tool": "issue_refund", "args": b[2]}), SIDE)
    assert [r.tool_use_id for r in p.results] == ["a", "c"]
    assert [(x.call_id, x.action) for x in p.pending] == [("b", "reconcile")]


def test_approvals():
    asked = {"kind": "approval_requested", "call_id": "c2", "tool": "issue_refund", "args": REFUND[2]}
    p = plan_recovery(J(asst(REFUND), asked), SIDE)
    assert p.status == "awaiting_approval" and p.pending[0].action == "await_approval"
    ok = {"kind": "approval", "call_id": "c2", "approved": True, "by": "maria", "note": ""}
    p = plan_recovery(J(asst(REFUND), asked, ok), SIDE)
    assert p.status == "resume" and p.pending[0].action == "execute"
    no = {"kind": "approval", "call_id": "c2", "approved": False, "by": "maria", "note": "over limit"}
    p = plan_recovery(J(asst(REFUND), asked, no), SIDE)
    assert p.status == "resume" and not p.pending and p.messages[-1].role == "user"
    denial = p.messages[-1].content[0]
    assert denial.is_error and "maria" in denial.text and "over limit" in denial.text


def test_done_and_purity():
    entries = J(asst(text="Refunded!"), {"kind": "end", "stop": "end_turn", "final_text": "Refunded!"})
    import copy
    before = copy.deepcopy(entries)
    p = plan_recovery(list(reversed(entries)), SIDE)
    assert p.status == "done" and not p.pending and entries == before


def test_sorts_by_seq():
    entries = J(asst(ELIG), {"kind": "intent", "call_id": "c1", "tool": ELIG[1], "args": ELIG[2]}, R("c1", "E"),
                asst(REFUND))
    p = plan_recovery(list(reversed(entries)), SIDE)
    assert [m.role for m in p.messages] == ["user", "assistant", "user", "assistant"]
    assert p.messages[2].content[0].text == "E" and [c.call_id for c in p.pending] == ["c2"]


def test_answered_but_crashed_before_end_is_done():
    p = plan_recovery(J(asst(ELIG), R("c1"), asst(text="All done.", stop="end_turn")), SIDE)
    assert p.status == "done" and not p.pending and p.messages[-1].text == "All done."
    p = plan_recovery(J(asst(ELIG), R("c1"), asst(text="All done.")), SIDE)
    assert p.status == "done", "no tool calls and no stop_reason: also finished"


def test_truncated_tool_calls_never_run():
    p = plan_recovery(J(asst(REFUND, stop="max_tokens")), SIDE)
    assert p.status == "done" and not p.pending


def test_pause_turn_continues():
    p = plan_recovery(J(asst(text="thinking...", stop="pause_turn")), SIDE)
    assert p.status == "resume" and not p.pending


def test_reused_call_ids_only_count_within_their_turn():
    """Turn 1 used id x and got a result; turn 2 reuses x for a refund whose intent has no result yet."""
    p = plan_recovery(J(asst(("x", "lookup_order", {"order_id": 4822})), R("x", "looked up"),
                        asst(("x", "issue_refund", {"order_id": 4822})),
                        {"kind": "intent", "call_id": "x", "tool": "issue_refund", "args": {"order_id": 4822}}), SIDE)
    assert p.status == "resume" and [(c.tool, c.action) for c in p.pending] == [("issue_refund", "reconcile")]
