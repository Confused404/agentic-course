"""The agent loop. AGENT-OFF (reference solution): written by hand in Node 02 YOU_DO task 3.

The dataclasses and the ToolExecutor protocol below are GIVEN (other code imports them). Implement
run_agent() to satisfy the contract in its docstring. Tests: nodes/02-agent-loop/tests/test_loop.py.
Read TEXTBOOK §2 (invariants), §3 (stop conditions), §6 (bounds), §7 (tracing) first.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from agentlab import tracing
from agentlab.costs import Budget, BudgetExceeded
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
    config = config or LoopConfig()
    # why: copy, never mutate the caller's history (contract 1); Message objects are copied shallowly
    # because we only ever append new messages, never edit old ones (append-only log, TEXTBOOK §2 inv. 1)
    msgs: list[Message] = [Message(m.role, list(m.content)) for m in messages]
    usage = Usage()
    records: list[ToolCallRecord] = []
    turns = 0
    cost = 0.0
    stop: Stop = "other"
    specs = tools.specs()

    with tracing.agent_span(config.agent_name):
        while True:
            if config.budget is not None:
                try:
                    config.budget.check()      # why: don't make a paid call we already can't afford
                except BudgetExceeded:
                    stop = "budget"
                    break
            with tracing.chat_span(model.provider, model.model) as span:
                resp = model.complete(system=system, messages=msgs, tools=specs,
                                      max_tokens=config.max_tokens, **config.model_opts)
                turns += 1
                usage = usage + resp.usage
                # why: append verbatim, incl. thinking blocks some vendors require back (TEXTBOOK §2 inv. 3)
                msgs.append(Message("assistant", list(resp.content)))
                call_cost = None
                if config.budget is not None:
                    before = config.budget.spent_usd
                    try:
                        call_cost = config.budget.charge(model.model, resp.usage, provider=model.provider)
                        cost += call_cost
                    except BudgetExceeded:
                        cost += config.budget.spent_usd - before
                        tracing.record_response(span, resp, config.budget.spent_usd - before)
                        stop = "budget"
                        break
                tracing.record_response(span, resp, call_cost)

            if resp.stop_reason == "pause_turn":
                if turns >= config.max_turns:
                    stop = "max_turns"
                    break
                continue          # a continuation, not an end (TEXTBOOK §3)
            if resp.stop_reason != "tool_use" or not resp.tool_calls:
                stop = {"end_turn": "end_turn", "stop_sequence": "end_turn", "max_tokens": "max_tokens",
                        "refusal": "refusal", "context_window_exceeded": "context_window_exceeded"
                        }.get(resp.stop_reason, "other") if resp.stop_reason != "tool_use" else "other"
                break

            # why: every call gets exactly one result, all in ONE user message, in call order (inv. 2 and 4)
            results: list[ToolResultBlock] = []
            for blk in resp.tool_calls:
                with tracing.tool_span(blk.name, blk.id, blk.input) as tspan:
                    if blk.parse_error:
                        res = ToolResultBlock(blk.id, f"Your arguments for {blk.name} were not valid JSON "
                                                      f"({blk.parse_error}). Call the tool again with a valid "
                                                      f"JSON object.", is_error=True)
                    else:
                        res = tools.execute(blk)
                    tracing.record_tool_result(tspan, res.text, res.is_error)
                results.append(res)
                records.append(ToolCallRecord(blk.name, blk.input, res.is_error, res.text[:200]))
            msgs.append(Message("user", results))

            if turns >= config.max_turns:
                stop = "max_turns"
                break

        # why: keep the transcript resumable: no tool call may be left without a result (contract 9)
        if msgs and msgs[-1].role == "assistant":
            pending = [b for b in msgs[-1].content if isinstance(b, ToolUseBlock)]
            if pending:
                msgs.append(Message("user", [ToolResultBlock(b.id, f"Not executed: {stop}", is_error=True)
                                             for b in pending]))

    last_assistant = next((m for m in reversed(msgs) if m.role == "assistant"), None)
    return LoopResult(messages=msgs, final_text=last_assistant.text if last_assistant else "", stop=stop,
                      turns=turns, usage=usage, tool_calls=records, cost_usd=cost)
