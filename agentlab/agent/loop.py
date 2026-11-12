"""The agent loop. AGENT-OFF: you write `run_agent` by hand (nodes/02-agent-loop/YOU_DO.md task 3).

The dataclasses and the ToolExecutor protocol below are GIVEN (other code imports them). Implement
run_agent() to satisfy the contract in its docstring. Tests: nodes/02-agent-loop/tests/test_loop.py.
Read TEXTBOOK §2 (invariants), §3 (stop conditions), §6 (bounds), §7 (tracing) first.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from agentlab.costs import Budget
from agentlab.llm.types import ChatModel, Message, TextBlock, ToolResultBlock, ToolSpec, ToolUseBlock, Usage

Stop = Literal["end_turn", "max_tokens", "refusal", "max_turns", "budget", "context_window_exceeded", "other"]


class ToolExecutor(Protocol):
    """What the loop needs from a set of tools (agentlab.tools.ToolRegistry implements it)."""

    def specs(self) -> list[ToolSpec]: ...

    def execute(self, call: ToolUseBlock) -> ToolResultBlock:
        """Run one call. Never raises: unknown tools, bad arguments and tool failures come back as
        ToolResultBlock(is_error=True) with an actionable message."""
        ...


@dataclass
class LoopConfig:
    max_turns: int = 10                 # model calls, not user turns
    max_tokens: int = 2048              # per model call (leave room for reasoning, Node 01 §6)
    budget: Budget | None = None        # None = no cost cap (tests only; live code always passes one)
    agent_name: str = "agent"           # used in the invoke_agent span name
    model_opts: dict = field(default_factory=dict)   # passed through to model.complete(**opts), e.g. effort


@dataclass
class ToolCallRecord:
    name: str
    input: dict
    is_error: bool
    result_preview: str                 # first 200 chars of the result text


@dataclass
class LoopResult:
    messages: list[Message]             # the FULL transcript: input messages + everything the loop appended
    final_text: str                     # text of the last assistant message ("" if none)
    stop: Stop
    turns: int                          # number of model calls made
    usage: Usage                        # summed over all model calls
    tool_calls: list[ToolCallRecord]    # every executed call, in order
    cost_usd: float = 0.0               # summed Budget charges (0.0 if no budget)


def run_agent(model: ChatModel, system: str | list[TextBlock], messages: list[Message],
              tools: ToolExecutor, config: LoopConfig | None = None) -> LoopResult:
    """Run the agent loop until it stops. Contract (each line is tested):

    1. Never mutate the caller's `messages` list or its Message objects; work on a copy.
    2. Each turn: call model.complete(system=..., messages=..., tools=tools.specs(),
       max_tokens=config.max_tokens, **config.model_opts). Append the assistant message with the
       response content VERBATIM (text, tool calls, thinking blocks, in order).
    3. If config.budget: BEFORE each model call, budget.check(); if it raises BudgetExceeded, stop with
       "budget" without calling. AFTER each call, charge it with
       budget.charge(model.model, response.usage, provider=model.provider); if that raises BudgetExceeded,
       stop with "budget" (the response that crossed the cap is already appended).
    4. If stop_reason == "tool_use": for each ToolUseBlock in order:
         - if block.parse_error is set: do NOT execute; result is an error ToolResultBlock telling the
           model its arguments were not valid JSON (include the parse error) and to retry;
         - else: result = tools.execute(block).
       Append ONE user message containing all results, in call order. Record a ToolCallRecord per call.
       Then continue to the next turn.
    5. "pause_turn" means continue (call the model again) without adding a user message.
    6. Otherwise stop. Map stop_reason: "end_turn"/"stop_sequence" -> "end_turn", "max_tokens" ->
       "max_tokens" (do NOT execute tool calls from a truncated response), "refusal" -> "refusal",
       "context_window_exceeded" -> "context_window_exceeded", anything else -> "other".
       A "tool_use" response with no tool calls in it is also "other".
    7. If the model has been called config.max_turns times and still wants tools, stop with
       "max_turns" (after appending the last assistant message and its tool results).
    8. Sum usage over all calls; final_text = text of the last assistant message.
    9. The transcript must always be resumable: on ANY stop, if the last message is an assistant message
       with tool calls that were not executed (budget stop, truncated response), append ONE user message
       with ToolResultBlock(id, "Not executed: <stop>", is_error=True) per call. Otherwise the next request
       has an unanswered tool call and the provider rejects it (TEXTBOOK §2 inv. 2, §3).
   10. Tracing: wrap the run in tracing.agent_span(config.agent_name); each model call in
       tracing.chat_span(model.provider, model.model) + tracing.record_response(span, resp, cost);
       each tool execution in tracing.tool_span(name, id, input) + tracing.record_tool_result(...).
    """
    raise NotImplementedError("AGENT-OFF: implement by hand (Node 02 YOU_DO task 3)")
