"""Anthropic Messages API <-> canonical types (TEXTBOOK §4). Two pure functions and a thin client wrapper."""
from __future__ import annotations

import time
from typing import Any

from agentlab.llm.types import (ImageBlock, Message, ModelResponse, TextBlock, ThinkingBlock, ToolResultBlock,
                                ToolSpec, ToolUseBlock, Usage)

_EPHEMERAL = {"type": "ephemeral"}
_STOP = {"end_turn", "tool_use", "max_tokens", "stop_sequence", "refusal", "pause_turn"}


def _text(b: TextBlock) -> dict:
    d: dict[str, Any] = {"type": "text", "text": b.text}
    if b.cache:
        d["cache_control"] = dict(_EPHEMERAL)
    return d


def _image(b: ImageBlock) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": b.media_type, "data": b.data_b64}}


def _block(b) -> dict | None:
    if isinstance(b, TextBlock):
        return _text(b)
    if isinstance(b, ImageBlock):
        return _image(b)
    if isinstance(b, ToolUseBlock):
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    if isinstance(b, ToolResultBlock):
        content = b.content if isinstance(b.content, str) else [_block(x) for x in b.content]
        return {"type": "tool_result", "tool_use_id": b.tool_use_id, "content": content, "is_error": b.is_error}
    if isinstance(b, ThinkingBlock):
        # why: signatures are only meaningful to the vendor that produced them; foreign reasoning is dropped
        if b.provider != "anthropic":
            return None
        data = b.provider_data or {}
        if "redacted_data" in data:
            return {"type": "redacted_thinking", "data": data["redacted_data"]}
        if not data.get("signature"):
            return None      # unsigned thinking can't be verified by the API; sending it is an error
        return {"type": "thinking", "thinking": b.text, "signature": data["signature"]}
    raise TypeError(f"unsupported block {type(b).__name__}")


def to_anthropic_request(*, model: str, system: str | list[TextBlock], messages: list[Message],
                         tools: list[ToolSpec] | None, max_tokens: int, opts: dict) -> tuple[dict, list[str]]:
    req: dict[str, Any] = {"model": model, "max_tokens": max_tokens}
    if isinstance(system, str):
        if system:
            req["system"] = system
    elif system:
        req["system"] = [_text(b) for b in system]
    req["messages"] = []
    for m in messages:
        content = [x for x in (_block(b) for b in m.content) if x is not None]
        # why: a turn that only held foreign reasoning would become empty, which the API rejects
        req["messages"].append({"role": m.role, "content": content or [{"type": "text", "text": "(no content)"}]})
    if tools:
        req["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools]
    dropped: list[str] = []
    output_config: dict[str, Any] = {}
    for k, v in opts.items():
        if k == "effort":
            output_config["effort"] = v
        elif k == "json_schema":
            output_config["format"] = {"type": "json_schema", "schema": v}
        elif k == "tool_choice":
            req["tool_choice"] = {"type": "tool", "name": v["name"]} if isinstance(v, dict) else {"type": v}
        elif k == "parallel_tools":
            if v is False:
                req.setdefault("tool_choice", {"type": "auto"})
                req["tool_choice"]["disable_parallel_tool_use"] = True
        elif k == "thinking":
            req["thinking"] = v
        elif k == "cache":
            if v:
                req["cache_control"] = dict(_EPHEMERAL)
        else:
            # why: current Claude models reject temperature/top_p; drop and report rather than 400 (TEXTBOOK §4)
            dropped.append(k)
    if "tool_choice" in req and opts.get("parallel_tools") is False:
        req["tool_choice"]["disable_parallel_tool_use"] = True   # in case tool_choice was set after parallel_tools
    if output_config:
        req["output_config"] = output_config
    return req, dropped


def from_anthropic_response(data: dict, latency_s: float = 0.0) -> ModelResponse:
    content = []
    for b in data.get("content") or []:
        t = b.get("type")
        if t == "text":
            content.append(TextBlock(b.get("text", "")))
        elif t == "tool_use":
            content.append(ToolUseBlock(b["id"], b["name"], b.get("input") or {}, provider="anthropic"))
        elif t == "thinking":
            content.append(ThinkingBlock(b.get("thinking", ""), provider="anthropic",
                                         provider_data={"signature": b.get("signature")}))
        elif t == "redacted_thinking":
            content.append(ThinkingBlock("", provider="anthropic", provider_data={"redacted_data": b.get("data")}))
    raw_stop = data.get("stop_reason")
    stop = raw_stop if raw_stop in _STOP else ("context_window_exceeded" if raw_stop == "model_context_window_exceeded"
                                               else "other")
    u = data.get("usage") or {}
    usage = Usage(input_tokens=u.get("input_tokens") or 0, output_tokens=u.get("output_tokens") or 0,
                  cache_read_tokens=u.get("cache_read_input_tokens") or 0,
                  cache_write_tokens=u.get("cache_creation_input_tokens") or 0,
                  reasoning_tokens=(u.get("output_tokens_details") or {}).get("thinking_tokens") or 0)
    return ModelResponse(content, stop, usage, data.get("model", ""), "anthropic", id=data.get("id"),
                         latency_s=latency_s, raw_stop_reason=raw_stop, raw=data)


class AnthropicModel:
    provider = "anthropic"

    def __init__(self, model: str, api_key: str | None = None, client: Any = None) -> None:
        self.model = model
        self._api_key = api_key
        self._client = client
        self.last_dropped_opts: list[str] = []

    @property
    def client(self):
        if self._client is None:
            import anthropic
            from agentlab.config import api_key
            self._client = anthropic.Anthropic(api_key=self._api_key or api_key("anthropic"))
        return self._client

    def complete(self, *, system: str | list[TextBlock], messages: list[Message], tools: list[ToolSpec] | None = None,
                 max_tokens: int = 1024, **opts: Any) -> ModelResponse:
        req, self.last_dropped_opts = to_anthropic_request(model=self.model, system=system, messages=messages,
                                                           tools=tools, max_tokens=max_tokens, opts=opts)
        t0 = time.perf_counter()
        data = self.client.messages.create(**req).model_dump()
        return from_anthropic_response(data, latency_s=time.perf_counter() - t0)
