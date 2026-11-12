"""The customer support assistant: a system prompt + bound tools + your agent loop + conversation history."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import uuid

from agentlab import tracing
from agentlab.agent.loop import LoopConfig, LoopResult, run_agent
from agentlab.assistant.prompts import SYSTEM_PROMPT_V1
from agentlab.assistant.tools import make_support_tools
from agentlab.costs import Budget
from agentlab.llm.types import ChatModel, Message
from shopfront import clock

FALLBACK_REPLY = "Sorry, I couldn't finish that. Please try again, or ask me to connect you with our support team."


@dataclass
class AssistantReply:
    reply: str
    result: LoopResult


class SupportAssistant:
    def __init__(self, model: ChatModel, conn: sqlite3.Connection, customer_id: int, budget: Budget | None = None,
                 max_turns: int = 8, model_opts: dict | None = None, system_prompt: str = SYSTEM_PROMPT_V1,
                 tool_variant: str = "v1") -> None:
        self.model, self.conn, self.customer_id = model, conn, customer_id
        self.budget, self.max_turns, self.model_opts = budget, max_turns, model_opts or {}
        self.system = system_prompt.format(today=clock.now().date().isoformat())
        self.tools = make_support_tools(conn, customer_id, variant=tool_variant)
        self.messages: list[Message] = []
        self.session_id = uuid.uuid4().hex     # groups this conversation's turns in traces (Node 04 flywheel)
        self.turn_index = 0

    def chat(self, user_text: str) -> AssistantReply:
        # one span per customer turn, carrying what the flywheel needs to rebuild a task (Node 04 §10)
        self.turn_index += 1
        with tracing.agent_span("support-chat", customer_id=self.customer_id, user_message=user_text,
                                session_id=self.session_id, turn_index=self.turn_index) as span:
            span.set_attribute("course.stop", "error")       # overwritten below unless run_agent raises
            self.messages.append(Message.user(user_text))
            result = run_agent(self.model, self.system, self.messages, self.tools,
                               LoopConfig(max_turns=self.max_turns, budget=self.budget, agent_name="support",
                                          model_opts=self.model_opts))
            span.set_attribute("course.stop", result.stop)
        self.messages = result.messages
        reply = result.final_text.strip()
        if result.stop not in ("end_turn", "refusal"):
            # why: "finished" vs "stopped" (TEXTBOOK §3). After max_turns/budget/etc. the last text is usually a
            # preamble ("Let me check..."), not an answer. Say honestly that we didn't finish, and don't
            # claim anything was recorded when nothing was.
            reply = FALLBACK_REPLY
        return AssistantReply(reply or FALLBACK_REPLY, result)
