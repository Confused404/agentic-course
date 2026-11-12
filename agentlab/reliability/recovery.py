"""What to do after a crash. AGENT-OFF: written by hand in Node 14 YOU_DO task 3.

PendingCall and RecoveryPlan are GIVEN (the durable runner imports them). Implement plan_recovery() to satisfy its
docstring. Tests: nodes/14-reliability/tests/test_recovery.py. Read TEXTBOOK §3-§4 first.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from agentlab.llm.types import Message, ToolResultBlock, ToolUseBlock  # noqa: F401 - you will need all three

Action = Literal["execute", "reconcile", "await_approval"]


@dataclass
class PendingCall:
    call_id: str
    tool: str
    args: dict
    action: Action              # execute: safe to run (again); reconcile: it may already have happened;
                                # await_approval: a human hasn't decided yet


@dataclass
class RecoveryPlan:
    status: Literal["done", "resume", "awaiting_approval"]
    messages: list[Message] = field(default_factory=list)     # the transcript to continue from
    results: list[ToolResultBlock] = field(default_factory=list)   # results already known for the open turn
    pending: list[PendingCall] = field(default_factory=list)       # calls of the open turn still to resolve, in order
    system: str = ""
    config: dict = field(default_factory=dict)


def plan_recovery(entries: list[dict], side_effect_tools: set[str]) -> RecoveryPlan:
    """Rebuild a run from its journal entries (see journal.py for the kinds) and decide what's left to do.
    Contract (each line is tested):

    1. Entries are processed in `seq` order (sort them; don't trust the list order). No "start" entry -> ValueError.
       system, config and the initial messages come from "start" (messages via Message.from_dict).
    2. An "end" entry -> status "done" (messages as rebuilt; nothing pending).
    3. Each "assistant" entry appends Message.from_dict(entry["message"]). Its tool calls (ToolUseBlocks, in order)
       form a TURN. Only entries AFTER that assistant entry (and before the next one) count for its calls: a call id
       reused in an earlier turn must not resolve a later call. A call is RESOLVED when it has a "result" entry
       (-> ToolResultBlock(call_id, content, is_error)) or an "approval" entry with approved=False
       (-> ToolResultBlock(call_id, "Denied by <by>: <note>", is_error=True)). When every call of a turn is
       resolved, append ONE user message with those results, in call order, before the next assistant message.
       A turn without tool calls appends nothing.
    4. The model already finished if the LAST assistant entry has no tool calls (and its "stop_reason", when
       present, isn't "pause_turn"), or its "stop_reason" is present and is neither "tool_use" nor "pause_turn"
       (e.g. "max_tokens": its tool calls may be truncated and must never run). Then status "done", nothing
       pending: the crash came after the answer but before "end" was written, and the runner just writes "end".
    5. Otherwise the last turn may be OPEN (some calls unresolved). Then `results` holds the resolved ones (in call
       order) and `pending` holds a PendingCall per unresolved call, in call order:
       - an "approval_requested" entry and no "approval" entry: action "await_approval";
       - an "intent" entry and no "result" entry: "reconcile" if the tool is in side_effect_tools (it may or may
         not have run before the crash), else "execute" (reads are safe to repeat);
       - otherwise (no intent yet, or approved): "execute".
       status = "awaiting_approval" if any pending call awaits approval, else "resume".
    6. No open turn, not finished, no end: status "resume" with nothing pending (the next step is a model call).
    7. Never mutate the entries.
    """
    raise NotImplementedError("AGENT-OFF: Node 14 YOU_DO task 3")
