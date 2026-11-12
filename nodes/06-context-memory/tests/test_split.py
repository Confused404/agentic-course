"""AGENT-OFF: split_for_compaction (YOU_DO task 2). These tests are the contract; write the function by hand."""
import pytest

from agentlab.context.split import is_customer_turn, split_for_compaction
from agentlab.llm.types import Message, TextBlock, ToolResultBlock, ToolUseBlock


def U(t):
    return Message.user(t)


def A(t):
    return Message("assistant", [TextBlock(t)])


def CALL(i, name="lookup_order"):
    return Message("assistant", [TextBlock("let me check"), ToolUseBlock(f"c{i}", name, {"order_id": i})])


def RES(i):
    return Message("user", [ToolResultBlock(f"c{i}", '{"status": "delivered"}')])


def convo(n_turns: int, tools_every: int = 2) -> list[Message]:
    out = []
    for k in range(n_turns):
        out.append(U(f"customer turn {k}"))
        if k % tools_every == 0:
            out += [CALL(k), RES(k)]
        out.append(A(f"answer {k}"))
    return out


def test_given_helper():
    assert is_customer_turn(U("hi")) and not is_customer_turn(RES(1)) and not is_customer_turn(A("x"))
    assert not is_customer_turn(U("   "))


def test_keep_turns_must_be_positive():
    with pytest.raises(ValueError):
        split_for_compaction(convo(3), 0)


def test_nothing_to_compact_when_few_turns():
    msgs = convo(3)
    old, kept = split_for_compaction(msgs, 3)
    assert old == [] and kept == msgs and kept is not msgs
    assert split_for_compaction([], 2) == ([], [])


def test_cut_at_the_kth_most_recent_customer_turn():
    msgs = convo(6)
    old, kept = split_for_compaction(msgs, 2)
    assert kept[0].text == "customer turn 4"
    assert sum(is_customer_turn(m) for m in kept) == 2
    assert all(not is_customer_turn(m) or m.text in ("customer turn 4", "customer turn 5") for m in kept)


def test_no_loss_no_copy_no_reorder():
    msgs = convo(7)
    snapshot = [m.to_dict() for m in msgs]
    old, kept = split_for_compaction(msgs, 3)
    assert old + kept == msgs
    assert all(a is b for a, b in zip(old + kept, msgs)), "same Message objects, not copies"
    assert [m.to_dict() for m in msgs] == snapshot, "input not mutated"


def test_tool_pairs_never_split():
    msgs = convo(8, tools_every=1)
    for k in range(1, 8):
        old, kept = split_for_compaction(msgs, k)
        used = {b.id for m in kept for b in m.content if isinstance(b, ToolUseBlock)}
        answered = {b.tool_use_id for m in kept for b in m.content if isinstance(b, ToolResultBlock)}
        assert answered <= used
        used_old = {b.id for m in old for b in m.content if isinstance(b, ToolUseBlock)}
        answered_old = {b.tool_use_id for m in old for b in m.content if isinstance(b, ToolResultBlock)}
        assert used_old <= answered_old


def test_tool_results_are_not_turns():
    # many tool rounds inside ONE customer turn: they all stay with that turn
    msgs = [U("turn 0"), A("a0"), U("turn 1"), CALL(1), RES(1), CALL(2), RES(2), CALL(3), RES(3), A("a1"),
            U("turn 2"), A("a2")]
    old, kept = split_for_compaction(msgs, 2)
    assert kept[0].text == "turn 1" and len(kept) == 10


def test_unanswered_call_in_old_is_rejected():
    msgs = [U("turn 0"), CALL(1), A("gave up"), U("turn 1"), A("a")]
    with pytest.raises(ValueError):
        split_for_compaction(msgs, 1)


def test_malformed_history_is_rejected():
    # a tool result in the kept part whose call was in the old part: can only happen if the history is broken
    msgs = [U("turn 0"), CALL(1), U("turn 1"), RES(1), A("a")]
    with pytest.raises(ValueError):
        split_for_compaction(msgs, 1)
