"""The LangGraph port's tool node. AGENT-OFF (reference solution): written by hand in Node 16 YOU_DO task 3.

Tests: nodes/16-frameworks/tests/test_graph_nodes.py. Read TEXTBOOK §4 first: on resume after an interrupt,
LangGraph re-runs the interrupted node FROM THE TOP. Whatever the node did before calling interrupt() happens again.
"""
from __future__ import annotations

from typing import Any, Callable

from langgraph.types import interrupt as lg_interrupt

from agentlab.llm.types import Message, ToolResultBlock, ToolUseBlock, to_dict  # noqa: F401


def tools_node(state: dict, *, registry: Any, approval_tools: set[str] | frozenset[str] = frozenset(),
               interrupt: Callable[[Any], Any] = lg_interrupt) -> dict:
    """Run the tool calls of the last assistant message. `state["messages"]` is a list of course message dicts
    (to_dict form); `registry` has .execute(ToolUseBlock) -> ToolResultBlock. Contract (each line is tested):

    1. Calls = the ToolUseBlocks of Message.from_dict(state["messages"][-1]) if that message is from the assistant,
       else none. No calls -> return {"messages": []}.
    2. BEFORE executing anything: if any call's name is in approval_tools, call interrupt() exactly ONCE with
       {"approvals": [{"call_id", "tool", "args"} for each such call, in call order]}. Its return value is the
       human's decisions: a dict call_id -> True/False, or call_id -> {"approved": bool, "by": str, "note": str}.
       A call with no decision counts as denied.
       (Why once and first: on resume the node runs again from the top, so a tool executed before the interrupt
       would run twice.)
    3. Then, in call order: a denied call -> ToolResultBlock(call_id, "Denied by <by>: <note>", is_error=True)
       ("a human" when there's no `by`; empty note allowed); a call with a parse_error -> an error result telling
       the model its arguments weren't valid JSON, NOT executed; anything else -> registry.execute(call).
    4. Return {"messages": [to_dict(Message("user", <the results, in call order>))]}.
    5. Never mutate the state.
    """
    msgs = state.get("messages") or []
    last = Message.from_dict(msgs[-1]) if msgs else None
    calls = [b for b in last.content if isinstance(b, ToolUseBlock)] if last and last.role == "assistant" else []
    if not calls:
        return {"messages": []}
    asks = [{"call_id": c.id, "tool": c.name, "args": dict(c.input)} for c in calls if c.name in approval_tools]
    decisions: dict = {}
    if asks:
        # ONE interrupt, before any tool runs: on resume the node restarts here, and nothing has happened yet
        decisions = interrupt({"approvals": asks}) or {}
    results = []
    for c in calls:
        if c.name in approval_tools:
            d = decisions.get(c.id, False)
            ok = d.get("approved", False) if isinstance(d, dict) else bool(d)
            if not ok:
                by = (d.get("by") if isinstance(d, dict) else None) or "a human"
                note = (d.get("note") if isinstance(d, dict) else "") or ""
                results.append(ToolResultBlock(c.id, f"Denied by {by}: {note}", is_error=True))
                continue
        if c.parse_error:
            results.append(ToolResultBlock(c.id, f"Your arguments for {c.name} were not valid JSON "
                                                 f"({c.parse_error}). Call the tool again with a JSON object.",
                                           is_error=True))
            continue
        results.append(registry.execute(c))
    return {"messages": [to_dict(Message("user", results))]}
