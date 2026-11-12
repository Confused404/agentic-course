"""AGENT-OFF: where to cut a conversation for compaction or a sliding window (Node 06 YOU_DO task 2).

Read TEXTBOOK §3 first. Tests: nodes/06-context-memory/tests/test_split.py.
`is_customer_turn` is GIVEN. You write `split_for_compaction` by hand: it is ~20 lines, and every context strategy in
this node (sliding window, compaction) relies on it being exactly right.
"""
from __future__ import annotations

from agentlab.llm.types import Message, TextBlock, ToolResultBlock


def is_customer_turn(m: Message) -> bool:
    """A message the CUSTOMER wrote: role user, some text, and no tool results.
    why: in the Messages format, tool results also travel as role="user" messages. Those are not turns; cutting
    just before one would orphan it from the assistant tool call it answers."""
    return (m.role == "user" and any(isinstance(b, TextBlock) and b.text.strip() for b in m.content)
            and not any(isinstance(b, ToolResultBlock) for b in m.content))


def split_for_compaction(messages: list[Message], keep_turns: int) -> tuple[list[Message], list[Message]]:
    """Split `messages` into (old, kept) so that `kept` holds the last `keep_turns` customer turns, verbatim.

    Contract (the tests check each item):
    1. keep_turns < 1 -> ValueError.
    2. If there are at most `keep_turns` customer turns, return ([], list(messages)): nothing to compact.
    3. Otherwise `kept` starts at the `keep_turns`-th most recent message for which is_customer_turn() is True,
       and `old` is everything before it.
    4. old + kept == messages: same Message objects, same order, nothing dropped or copied. Don't mutate anything.
    5. Pairing: every ToolResultBlock in `kept` answers a ToolUseBlock that is also in `kept`, and every ToolUseBlock
       in `old` is answered in `old`. (If you cut only at customer turns, this holds for well-formed histories.
       Check it anyway, and raise ValueError if the history is malformed: a strategy must never send an orphaned
       tool result, which providers reject.)
    """
    raise NotImplementedError("AGENT-OFF: write split_for_compaction (Node 06 YOU_DO task 2)")
