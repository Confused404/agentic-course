"""Token estimates and a context breakdown (Node 06 §2).

The estimate is deliberately crude (characters / 4 over the JSON the adapter would send). It is good enough to
decide WHEN to compact, which only needs to be right within ~20%. For exact counts, use the provider's usage on the
response (what you were billed) or its token-counting endpoint (APPENDIX). Calibrate the ratio on your own traffic
(YOU_DO task 4): it differs by language, by vendor tokenizer, and for JSON-heavy tool results.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict

from agentlab.llm.types import Message, TextBlock, ThinkingBlock, ToolResultBlock, ToolSpec, ToolUseBlock

CHARS_PER_TOKEN = 4.0


def _est(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN) if text else 0


def estimate_tokens(obj) -> int:
    """str -> its length; Message/ToolSpec/list -> the JSON of their dict form."""
    if obj is None:
        return 0
    if isinstance(obj, str):
        return _est(obj)
    if isinstance(obj, Message):
        return _est(json.dumps(obj.to_dict(), ensure_ascii=False))
    if isinstance(obj, ToolSpec):
        return _est(json.dumps(asdict(obj), ensure_ascii=False))
    if isinstance(obj, (list, tuple)):
        return sum(estimate_tokens(x) for x in obj)
    return _est(json.dumps(obj, ensure_ascii=False, default=str))


def estimate_request(system: str, tools: list[ToolSpec], messages: list[Message]) -> int:
    return estimate_tokens(system) + estimate_tokens(tools) + estimate_tokens(messages)


def _block_text(b) -> str:
    if isinstance(b, (TextBlock, ThinkingBlock)):
        return b.text
    if isinstance(b, ToolUseBlock):
        return json.dumps({"name": b.name, "input": b.input}, ensure_ascii=False)
    if isinstance(b, ToolResultBlock):
        return b.content if isinstance(b.content, str) else json.dumps([getattr(x, "text", "") for x in b.content])
    return ""


def breakdown(system: str, tools: list[ToolSpec], messages: list[Message]) -> dict[str, int]:
    """Estimated tokens by component. why: you can't manage what you don't measure; in most agents the biggest
    line is tool results, not the conversation itself (TEXTBOOK §2)."""
    out = {"system": estimate_tokens(system), "tools": estimate_tokens(tools), "customer_text": 0,
           "assistant_text": 0, "thinking": 0, "tool_calls": 0, "tool_results": 0}
    for m in messages:
        for b in m.content:
            n = _est(_block_text(b))
            if isinstance(b, ToolResultBlock):
                out["tool_results"] += n
            elif isinstance(b, ToolUseBlock):
                out["tool_calls"] += n
            elif isinstance(b, ThinkingBlock):
                out["thinking"] += n
            elif isinstance(b, TextBlock):
                out["customer_text" if m.role == "user" else "assistant_text"] += n
    out["total"] = sum(out.values())
    return out
