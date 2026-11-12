"""A scripted, offline ChatModel for tests and CI.

Why a scripted fake instead of recorded responses ("cassettes")? A cassette replays what a real
model said for an exact prompt; the moment you edit the prompt, the cassette is stale. A script
says "on turn N, respond with X", which tests YOUR control flow (the loop, tool dispatch, state
changes, budgets) independently of model quality. Model quality is measured separately by live
evals (Node 04 §6). Two different questions, two different tools.

Usage:
    model = ScriptedModel([
        call("lookup_order", order_id=4821),             # turn 1: model asks for a tool
        say("Your order was delivered 45 days ago."),    # turn 2: model answers
    ])
Each step may also be a function (system, messages, tools, opts) -> ModelResponse, for steps
that must react to what the code under test sent (e.g. "echo the tool result").
Use fail(exc) as a step to make that turn raise (rate limits, overloads: Node 14).

Tool-use ids are rewritten per model instance as toolu_fake_<turn>_<k>, so they're
deterministic no matter how many scripts other tests built.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Union

from agentlab.llm.types import (Message, ModelResponse, TextBlock, ThinkingBlock, ToolResultBlock, ToolSpec,
                                ToolUseBlock, Usage)

Step = Union[ModelResponse, "Failure", Callable[..., ModelResponse]]


class ScriptExhausted(BaseException):
    """The code under test called the model more times than the script allows (a runaway loop?).

    Deliberately a BaseException: a retry loop's `except Exception` must not swallow it."""


@dataclass
class Failure:
    exc: BaseException


def fail(exc: BaseException) -> Failure:
    return Failure(exc)


def _usage(text: str, usage: Usage | None) -> Usage:
    return copy.deepcopy(usage) if usage else Usage(input_tokens=100, output_tokens=max(1, len(text) // 4))


def say(text: str, *, usage: Usage | None = None) -> ModelResponse:
    return ModelResponse([TextBlock(text)], "end_turn", _usage(text, usage), "scripted", "fake")


def call(tool: str, /, _preamble: str = "", *, _usage_override: Usage | None = None, **tool_input: Any) -> ModelResponse:
    """One tool call. `tool` is positional-only, so tools with an argument called `name` work."""
    blocks = ([TextBlock(_preamble)] if _preamble else []) + [ToolUseBlock("toolu_fake", tool, tool_input)]
    return ModelResponse(blocks, "tool_use", _usage(tool + str(tool_input), _usage_override), "scripted", "fake")


def calls(*pairs: tuple[str, dict]) -> ModelResponse:
    """Several tool calls in one turn (parallel tool use)."""
    blocks = [ToolUseBlock("toolu_fake", n, i) for n, i in pairs]
    return ModelResponse(blocks, "tool_use", _usage(str(pairs), None), "scripted", "fake")


def bad_call(tool: str, raw_arguments: str) -> ModelResponse:
    """A tool call whose arguments failed to parse (what an adapter returns for malformed JSON)."""
    blk = ToolUseBlock("toolu_fake", tool, {}, raw_arguments=raw_arguments, parse_error="invalid JSON")
    return ModelResponse([blk], "tool_use", _usage(raw_arguments, None), "scripted", "fake")


def think(text: str, then: ModelResponse, provider: str = "fake") -> ModelResponse:
    """Prefix a response with a reasoning block that the code under test must round-trip."""
    r = copy.deepcopy(then)
    r.content.insert(0, ThinkingBlock(text, provider=provider, provider_data={"signature": "sig-" + text[:8]}))
    return r


def truncated(text: str) -> ModelResponse:
    return ModelResponse([TextBlock(text)], "max_tokens", _usage(text, None), "scripted", "fake")


def refuse(text: str = "I can't help with that.") -> ModelResponse:
    return ModelResponse([TextBlock(text)], "refusal", _usage(text, None), "scripted", "fake")


def last_tool_results(messages: list[Message]) -> list[ToolResultBlock]:
    """Helper for callable steps: the tool results the loop just sent back."""
    if not messages:
        return []
    return [b for b in messages[-1].content if isinstance(b, ToolResultBlock)]


@dataclass
class ScriptedModel:
    script: list[Step]
    provider: str = "fake"
    model: str = "scripted"
    calls: list[dict] = field(default_factory=list)   # what the code under test sent, per turn

    def complete(self, *, system: str | list[TextBlock], messages: list[Message],
                 tools: list[ToolSpec] | None = None, max_tokens: int = 1024, **opts: Any) -> ModelResponse:
        self.calls.append({"system": copy.deepcopy(system), "messages": copy.deepcopy(messages),
                           "tools": [t.name for t in (tools or [])], "tool_specs": copy.deepcopy(tools or []),
                           "max_tokens": max_tokens, "opts": opts})
        i = len(self.calls) - 1
        if i >= len(self.script):
            raise ScriptExhausted(f"Model called {i + 1} times but script has {len(self.script)} steps.")
        step = self.script[i]
        if isinstance(step, Failure):
            raise step.exc
        resp = step(system, messages, tools, opts) if callable(step) else copy.deepcopy(step)
        k = 0
        for b in resp.content:
            if isinstance(b, ToolUseBlock):
                b.id = f"toolu_fake_{i + 1}_{k}"
                k += 1
        resp.id = resp.id or f"msg_fake_{i + 1}"
        return resp
