"""The customer support assistant: a system prompt + bound tools + your agent loop + conversation history.

Node 06 adds three things, all off by default (so Nodes 02-05 behave exactly as before):
- a context strategy: what part of the history is sent on each call (`context="full"` = everything);
- long-term memory: read at session start, written at end_session() (`memory="off" | "read" | "on"`);
- case notes: a tool the model uses to write down what it must not forget (`notes=True`).
It also separates the TRANSCRIPT (everything that happened, for graders, audits and memory extraction) from the
WORKING history (what the model is shown). Compaction edits the second, never the first.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass

from agentlab import tracing
from agentlab.agent.loop import LoopConfig, LoopResult, run_agent
from agentlab.assistant.prompts import SYSTEM_PROMPT_V1
from agentlab.assistant.tools import make_support_tools
from agentlab.context.strategies import ContextStrategy, make_strategy
from agentlab.costs import Budget
from agentlab.llm.types import ChatModel, Message, TextBlock
from agentlab.tools.base import Tool
from agentlab.tools.errors import ToolError
from shopfront import clock

FALLBACK_REPLY = "Sorry, I couldn't finish that. Please try again, or ask me to connect you with our support team."
MEMORY_MODES = ("off", "read", "on")
MAX_NOTES = 2000


@dataclass
class AssistantReply:
    reply: str
    result: LoopResult


class SupportAssistant:
    def __init__(self, model: ChatModel, conn: sqlite3.Connection, customer_id: int, budget: Budget | None = None,
                 max_turns: int = 8, model_opts: dict | None = None, system_prompt: str = SYSTEM_PROMPT_V1,
                 tool_variant: str = "v1", context: str | ContextStrategy = "full", memory: str = "off",
                 notes: bool = False, summarizer: ChatModel | None = None,
                 memory_model: ChatModel | None = None) -> None:
        if memory not in MEMORY_MODES:
            raise ValueError(f"memory must be one of {MEMORY_MODES}, got {memory!r}")
        self.model, self.conn, self.customer_id = model, conn, customer_id
        self.budget, self.max_turns, self.model_opts = budget, max_turns, model_opts or {}
        self.memory_mode, self.memory_model = memory, memory_model or model
        self.system = system_prompt.format(today=clock.now().date().isoformat())
        tools = make_support_tools(conn, customer_id, variant=tool_variant)
        extra: list[Tool] = []
        self.memory = None
        if memory != "off":
            from agentlab.memory.store import MemoryStore, render_memory_block
            from agentlab.memory.tools import make_memory_tools
            self.memory = MemoryStore(conn)
            block = render_memory_block(self.memory.active(customer_id))
            if block:
                # why at the END: per-customer content after the shared prompt keeps the shared prefix cacheable
                self.system += "\n\n" + block
            extra += make_memory_tools(self.memory, customer_id)
        self.notes_enabled, self.notes = notes, ""
        if notes:
            extra.append(self._notes_tool())
        self.tools = tools.with_tools(extra) if extra else tools
        self.strategy = (make_strategy(context, summarizer or model, budget) if isinstance(context, str)
                         else context)
        self.messages: list[Message] = []      # WORKING history: what the model is shown (strategies edit it)
        self.transcript: list[Message] = []    # everything that happened, append-only
        self.turn_stats: list[dict] = []
        from agentlab.context.tokens import estimate_tokens
        # the fixed part of every request, for the context breakdown (it doesn't change within a session)
        self.fixed_tokens = {"system": estimate_tokens(self.system), "tools": estimate_tokens(self.tools.specs())}
        self.session_id = uuid.uuid4().hex     # groups this conversation's turns in traces (Node 04 flywheel)
        self.turn_index = 0

    def _notes_tool(self) -> Tool:
        def update_case_notes(notes: str):
            if len(notes) > MAX_NOTES:
                raise ToolError(f"Notes are {len(notes)} characters; the limit is {MAX_NOTES}. Shorten them: keep "
                                f"customer instructions, order numbers and open items; drop what tools can look up.")
            self.notes = notes
            return json.dumps({"saved": True, "chars": len(notes)})
        return Tool("update_case_notes",
                    "Save notes for the rest of THIS conversation: the customer's instructions and rules, facts they "
                    "told you that tools can't look up, names they gave to orders, and open items. Older messages "
                    "may be removed from your view in long conversations; these notes are always shown at the "
                    "start. Replaces the previous notes, so include everything still relevant. Returns {saved, "
                    "chars}.",
                    {"type": "object", "properties": {"notes": {"type": "string", "description":
                     "the complete notes, e.g. '- Rule: no refunds unless the message says CONFIRM\\n- 4831 = "
                     "\"the birthday order\"'"}}, "required": ["notes"], "additionalProperties": False},
                    update_case_notes, side_effects=False)

    def _with_notes(self, working: list[Message]) -> list[Message]:
        if not (self.notes_enabled and self.notes and working):
            return working
        first = working[0]
        safe = self.notes.replace("</case_notes>", "</case_notes_>")    # notes can't close their own tag
        head = TextBlock(f"<case_notes>\n[Your own notes for this conversation so far, shown on every call.]\n{safe}\n"
                         f"</case_notes>\n\n")
        return [Message(first.role, [head, *first.content]), *working[1:]]

    def chat(self, user_text: str) -> AssistantReply:
        # one span per customer turn, carrying what the flywheel needs to rebuild a task (Node 04 §10)
        self.turn_index += 1
        with tracing.agent_span("support-chat", customer_id=self.customer_id, user_message=user_text,
                                session_id=self.session_id, turn_index=self.turn_index) as span:
            span.set_attribute("course.stop", "error")       # overwritten below unless run_agent raises
            user = Message.user(user_text)
            self.transcript.append(user)      # first: if the agent fails, the record still shows what was asked
            working = self.strategy.prepare(self.messages + [user], system=self.system, tools=self.tools.specs())
            prep = self.strategy.history[-1] if self.strategy.history else None
            send = self._with_notes(working)
            result = run_agent(self.model, self.system, send, self.tools,
                               LoopConfig(max_turns=self.max_turns, budget=self.budget, agent_name="support",
                                          model_opts=self.model_opts))
            span.set_attribute("course.stop", result.stop)
            if prep:
                span.set_attribute("course.context_action", prep.action)
        new = result.messages[len(send):]
        self.messages = working + new          # notes are re-injected per call, never stored in the history
        self.transcript += new
        u = result.usage
        self.turn_stats.append({"turn": self.turn_index, "calls": result.turns, "input_tokens": u.total_input,
                                "cache_read_tokens": u.cache_read_tokens, "output_tokens": u.output_tokens,
                                "est_before": prep.before_tokens if prep else None,
                                "est_after": prep.after_tokens if prep else None,
                                "action": prep.action if prep else "none",
                                "detail": prep.detail if prep else ""})
        if prep and prep.action == "compacted" and getattr(self.strategy, "summaries", None):
            # why: "read the summary the model actually saw" is the first debugging step for compaction (§4)
            self.turn_stats[-1]["summary"] = self.strategy.summaries[-1]
        reply = result.final_text.strip()
        if result.stop not in ("end_turn", "refusal"):
            # why: "finished" vs "stopped" (Node 02 TEXTBOOK §3). After max_turns/budget/etc. the last text is
            # usually a preamble ("Let me check..."), not an answer.
            reply = FALLBACK_REPLY
        return AssistantReply(reply or FALLBACK_REPLY, result)

    def end_session(self) -> list:
        """Write path for long-term memory (memory="on"): extract, filter with memory_policy, store. Returns the
        write log (what was proposed, what the policy decided). No-op otherwise."""
        if self.memory_mode != "on" or self.memory is None or not self.transcript:
            return []
        from agentlab.memory.extract import consolidate
        return consolidate(self.memory, self.customer_id, self.transcript, self.memory_model,
                           session_id=self.session_id, budget=self.budget)
