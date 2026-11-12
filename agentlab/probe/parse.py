"""Pure parsers for raw vendor payloads. No network, no SDK imports: testable on recorded JSON.

Both return the same shape so experiments can compare vendors row by row:
    {"text", "tool_calls": [{"id","name","arguments","raw_arguments","parse_error"}], "stop_reason", "usage", "model"}
"""
from __future__ import annotations

import json

from agentlab.llm.types import Usage


def parse_anthropic(msg: dict) -> dict:
    text, calls = [], []
    for block in msg.get("content") or []:
        if block.get("type") == "text":
            text.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            # why: Anthropic sends tool input as a JSON *object*, already parsed by the server (TEXTBOOK §9)
            calls.append({"id": block.get("id"), "name": block.get("name"), "arguments": block.get("input"),
                          "raw_arguments": None, "parse_error": None})
        # thinking / redacted_thinking blocks: their cost is in usage.output_tokens; content not needed here
    u = msg.get("usage") or {}
    usage = Usage(input_tokens=u.get("input_tokens") or 0, output_tokens=u.get("output_tokens") or 0,
                  cache_read_tokens=u.get("cache_read_input_tokens") or 0,
                  cache_write_tokens=u.get("cache_creation_input_tokens") or 0,
                  # why: thinking is billed as output; the breakdown tells you how much of it was thinking (§6)
                  reasoning_tokens=(u.get("output_tokens_details") or {}).get("thinking_tokens") or 0)
    return {"text": "".join(text), "tool_calls": calls, "stop_reason": msg.get("stop_reason") or "",
            "usage": usage, "model": msg.get("model", "")}


def _parse_args(raw: str | None) -> tuple[dict | None, str | None]:
    # why: OpenAI-format arguments are a model-generated STRING. It can be truncated, invalid, or valid
    # JSON that isn't an object. Capture the failure as data; never crash the experiment (TEXTBOOK §9).
    if raw is None or raw == "":
        return {}, None
    try:
        val = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"
    if not isinstance(val, dict):
        return None, f"arguments must be a JSON object, got {type(val).__name__}"
    return val, None


def parse_openai(completion: dict) -> dict:
    choices = completion.get("choices") or [{}]
    choice = choices[0] or {}
    message = choice.get("message") or {}
    calls = []
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function") or {}
        raw = fn.get("arguments")
        args, err = _parse_args(raw)
        calls.append({"id": tc.get("id"), "name": fn.get("name"), "arguments": args, "raw_arguments": raw,
                      "parse_error": err})
    finish = choice.get("finish_reason") or ""
    # why: some local runtimes report "stop" even when the turn contains tool calls; normalize on content
    stop = "tool_calls" if calls else finish

    u = completion.get("usage") or {}
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    reasoning = (u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
    prompt = u.get("prompt_tokens") or 0
    usage = Usage(input_tokens=prompt - cached, output_tokens=u.get("completion_tokens") or 0,
                  cache_read_tokens=cached, reasoning_tokens=reasoning, cost_usd=u.get("cost"))
    return {"text": message.get("content") or "", "tool_calls": calls, "stop_reason": stop, "usage": usage,
            "model": completion.get("model", "")}
