"""The support assistant as a LangGraph graph (Node 16 TEXTBOOK §4).

LangGraph is an orchestration framework, not a model client: the "agent" node calls the course's own ChatModel
(Node 02 adapters, budget, tracing all unchanged) and the "tools" node is your tools_node. LangGraph contributes the
state machine, a checkpointer that saves the state after every step, and interrupt() for human approval.

    START -> agent --(tool calls)--> tools -> agent ... --(no tool calls / limit)--> END
"""
from __future__ import annotations

import operator
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from agentlab import tracing
from agentlab.assistant.prompts import get_prompt
from agentlab.assistant.tools import make_support_tools
from agentlab.costs import Budget
from agentlab.frameworks import graph_nodes as nodes_module
from agentlab.llm.types import Message, Usage, to_dict
from shopfront import clock

STOPS = {"end_turn": "end_turn", "stop_sequence": "end_turn", "max_tokens": "max_tokens", "refusal": "refusal",
         "context_window_exceeded": "context_window_exceeded"}


class State(TypedDict, total=False):
    messages: Annotated[list, operator.add]      # course message dicts; nodes return what to APPEND
    usage: Annotated[list, operator.add]         # one Usage dict per model call
    stop: str                                    # the last agent step's outcome


def calls_this_turn(messages: list[dict]) -> int:
    """Assistant messages since the customer's last message (a user message with text, not just tool results)."""
    n = 0
    for m in reversed(messages):
        if m["role"] == "assistant":
            n += 1
        elif any(b.get("type") == "text" for b in m["content"]):
            break
    return n


def build_graph(model, registry, system: str, *, budget: Budget | None = None, max_calls: int = 8,
                approval_tools: frozenset[str] = frozenset(), checkpointer=None, model_opts: dict | None = None):
    def agent(state: State) -> dict:
        if calls_this_turn(state["messages"]) >= max_calls:
            return {"stop": "max_turns"}
        if budget is not None:
            budget.check()
        msgs = [Message.from_dict(m) for m in state["messages"]]
        with tracing.chat_span(model.provider, model.model) as span:
            resp = model.complete(system=system, messages=msgs, tools=registry.specs(), max_tokens=2048,
                                  **(model_opts or {}))
            cost = budget.charge(model.model, resp.usage, provider=model.provider) if budget else None
            tracing.record_response(span, resp, cost)
        msg = Message("assistant", list(resp.content))
        stop = "tool_use" if resp.stop_reason == "tool_use" and resp.tool_calls else \
            STOPS.get(resp.stop_reason, "other")
        return {"messages": [to_dict(msg)], "stop": stop, "usage": [dict(resp.usage.__dict__)]}

    def tools(state: State) -> dict:
        return nodes_module.tools_node(state, registry=registry, approval_tools=approval_tools)

    def route(state: State) -> str:
        return "tools" if state.get("stop") == "tool_use" else END

    g = StateGraph(State)
    g.add_node("agent", agent)
    g.add_node("tools", tools)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route, ["tools", END])
    g.add_edge("tools", "agent")
    return g.compile(checkpointer=checkpointer or InMemorySaver())


def sqlite_checkpointer(path: str | Path):
    """A checkpointer that survives the process (langgraph-checkpoint-sqlite)."""
    from langgraph.checkpoint.sqlite import SqliteSaver
    saver = SqliteSaver(sqlite3.connect(str(path), check_same_thread=False))
    saver.setup()
    return saver


@dataclass
class GraphResult:
    stop: str
    turns: int
    usage: Usage = field(default_factory=Usage)
    final_text: str = ""
    interrupts: list = field(default_factory=list)


@dataclass
class GraphReply:
    reply: str
    result: GraphResult


FALLBACK_REPLY = "Sorry, I couldn't finish that. A colleague will follow up."


def _result(app, config, start_len: int, usage0: int) -> tuple[GraphResult, list[Message]]:
    snap = app.get_state(config)
    vals = snap.values
    new = [Message.from_dict(m) for m in vals.get("messages", [])[start_len:]]
    usage = Usage()
    for u in vals.get("usage", [])[usage0:]:
        usage = usage + Usage(**u)
    interrupts = [i.value for t in snap.tasks for i in (t.interrupts or [])]
    stop = "awaiting_approval" if interrupts else vals.get("stop") or "other"
    if stop == "tool_use":
        stop = "other"
    final = new[-1].text if new and new[-1].role == "assistant" else ""
    turns = sum(m.role == "assistant" for m in new)
    return GraphResult(stop, turns, usage, final, interrupts), new


class GraphSupportAssistant:
    """Node 04's eval contract on LangGraph: one thread per conversation."""

    def __init__(self, model, conn, customer_id: int, budget: Budget | None = None, *, max_calls: int = 8,
                 system_prompt: str | None = None, tool_variant: str = "v2", checkpointer=None,
                 approval_tools: frozenset[str] = frozenset(), thread_id: str | None = None) -> None:
        import uuid
        system = (system_prompt or get_prompt("v2")).format(today=clock.now().date().isoformat())
        self.registry = make_support_tools(conn, customer_id, actor="agent:langgraph", variant=tool_variant)
        self.app = build_graph(model, self.registry, system, budget=budget, max_calls=max_calls,
                               approval_tools=approval_tools, checkpointer=checkpointer)
        self.config = {"configurable": {"thread_id": thread_id or uuid.uuid4().hex}}
        self.transcript: list[Message] = []
        self.turn_stats: list[dict] = []
        self.fixed_tokens: dict = {}

    def _counts(self) -> tuple[int, int]:
        vals = self.app.get_state(self.config).values
        return len(vals.get("messages", [])), len(vals.get("usage", []))

    def _finish(self, start_len: int, usage0: int) -> GraphReply:
        res, new = _result(self.app, self.config, start_len, usage0)
        self.transcript += new
        self.turn_stats.append({"turn": len(self.turn_stats) + 1, "calls": res.turns,
                                "input_tokens": res.usage.total_input, "output_tokens": res.usage.output_tokens,
                                "cache_read_tokens": res.usage.cache_read_tokens, "action": "none"})
        reply = res.final_text.strip() if res.stop == "end_turn" and res.final_text.strip() else FALLBACK_REPLY
        return GraphReply(reply, res)

    def chat(self, user_text: str) -> GraphReply:
        if self.pending_approvals():
            # why refuse: the last assistant message has tool calls without results; appending a user message
            # would make an invalid transcript (providers reject it). The approval must be answered first.
            return GraphReply("Your request is waiting for a colleague's approval; we'll get back to you.",
                              GraphResult("awaiting_approval", 0))
        start_len, usage0 = self._counts()
        try:
            with tracing.agent_span("support-chat-langgraph"):
                self.app.invoke({"messages": [to_dict(Message.user(user_text))], "stop": ""}, self.config)
        finally:
            reply = self._finish(start_len, usage0)    # the checkpointed part of a failed turn still counts
        return reply

    def pending_approvals(self) -> list[dict]:
        snap = self.app.get_state(self.config)
        return [a for t in snap.tasks for i in (t.interrupts or []) for a in i.value.get("approvals", [])]

    def resume(self, decisions: dict) -> GraphReply:
        """Continue after an interrupt with {call_id: True/False or {"approved", "by", "note"}}."""
        start_len, usage0 = self._counts()
        try:
            with tracing.agent_span("support-chat-langgraph-resume"):
                self.app.invoke(Command(resume=decisions), self.config)
        finally:
            reply = self._finish(start_len, usage0)
        return reply
