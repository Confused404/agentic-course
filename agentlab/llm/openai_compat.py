"""OpenAI-compatible Chat Completions (OpenRouter, Ollama, OpenAI) <-> canonical types (TEXTBOOK §4).

This is the lossy direction: canonical blocks are richer than Chat Completions messages.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from agentlab.llm.types import (ImageBlock, Message, ModelResponse, TextBlock, ThinkingBlock, ToolResultBlock,
                                ToolSpec, ToolUseBlock, Usage)


def _system_text(system: str | list[TextBlock]) -> str:
    # why: Chat Completions has one system string; block-level cache flags have nowhere to go
    return system if isinstance(system, str) else "\n\n".join(b.text for b in system)


def _user_content(blocks: list) -> str | list[dict] | None:
    if not blocks:
        return None
    if all(isinstance(b, TextBlock) for b in blocks):
        return "".join(b.text for b in blocks)
    parts = []
    for b in blocks:
        if isinstance(b, TextBlock):
            parts.append({"type": "text", "text": b.text})
        elif isinstance(b, ImageBlock):
            parts.append({"type": "image_url", "image_url": {"url": f"data:{b.media_type};base64,{b.data_b64}"}})
    return parts


def _convert_message(m: Message, provider: str) -> list[dict]:
    if m.role == "assistant":
        text = "".join(b.text for b in m.content if isinstance(b, TextBlock))
        out: dict[str, Any] = {"role": "assistant", "content": text or None}
        calls = [b for b in m.content if isinstance(b, ToolUseBlock)]
        if calls:
            out["tool_calls"] = [{"id": c.id, "type": "function", "function": {
                "name": c.name,
                # why: if the model's JSON was broken, send back exactly what it wrote (the error result refers to it)
                "arguments": c.raw_arguments if c.parse_error else json.dumps(c.input)}} for c in calls]
        for b in m.content:
            if isinstance(b, ThinkingBlock) and b.provider == provider and (b.provider_data or {}).get("reasoning_details"):
                out["reasoning_details"] = b.provider_data["reasoning_details"]
        if out["content"] is None and not calls:
            out["content"] = ""    # why: an assistant message with neither content nor tool_calls is rejected
        return [out]
    msgs: list[dict] = []
    rest: list = []
    for b in m.content:
        if isinstance(b, ToolResultBlock):
            text = ("ERROR: " if b.is_error else "") + b.text
            msgs.append({"role": "tool", "tool_call_id": b.tool_use_id, "content": text})
            if not isinstance(b.content, str):
                rest += [x for x in b.content if isinstance(x, ImageBlock)]   # images can't ride in tool messages
        else:
            rest.append(b)
    user = _user_content([b for b in rest if isinstance(b, (TextBlock, ImageBlock))])
    if user:
        msgs.append({"role": "user", "content": user})
    return msgs


def to_openai_request(*, model: str, system: str | list[TextBlock], messages: list[Message],
                      tools: list[ToolSpec] | None, max_tokens: int, opts: dict,
                      provider: str) -> tuple[dict, list[str]]:
    msgs: list[dict] = []
    sys_text = _system_text(system)
    if sys_text:
        msgs.append({"role": "system", "content": sys_text})
    for m in messages:
        msgs += _convert_message(m, provider)
    # why: OpenAI's own API deprecated max_tokens (reasoning models reject it); OpenRouter and Ollama accept it
    req: dict[str, Any] = {"model": model, "messages": msgs,
                           ("max_completion_tokens" if provider == "openai" else "max_tokens"): max_tokens}
    extra_body: dict[str, Any] = {}
    if tools:
        req["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                          "parameters": t.input_schema}} for t in tools]
    dropped: list[str] = []
    for k, v in opts.items():
        if k == "effort":
            if provider == "openrouter":
                extra_body["reasoning"] = {"effort": v}     # OpenRouter's unified reasoning control
            else:
                req["reasoning_effort"] = v
        elif k == "parallel_tools":
            req["parallel_tool_calls"] = bool(v)
        elif k in ("temperature", "top_p", "seed"):
            req[k] = v
        elif k == "json_schema":
            req["response_format"] = {"type": "json_schema", "json_schema": {"name": "output", "schema": v, "strict": True}}
        elif k == "tool_choice":
            if isinstance(v, dict):
                req["tool_choice"] = {"type": "function", "function": {"name": v["name"]}}
            else:
                req["tool_choice"] = "required" if v == "any" else v
        elif k == "fallback_models" and provider == "openrouter":
            # why the primary goes first: OpenRouter's `models` list replaces `model` as the order to try
            extra_body["models"] = [model, *v]
        else:
            dropped.append(k)        # includes "cache": automatic on these providers
    if provider == "openrouter":
        extra_body["usage"] = {"include": True}
    if extra_body:
        req["extra_body"] = extra_body
    return req, dropped


def _parse_args(raw: str | None) -> tuple[dict, str | None]:
    if raw is None or raw == "":
        return {}, None
    try:
        v = json.loads(raw)
    except json.JSONDecodeError as e:
        return {}, f"invalid JSON: {e}"
    if not isinstance(v, dict):
        return {}, f"arguments must be a JSON object, got {type(v).__name__}"
    return v, None


def from_openai_response(data: dict, provider: str, latency_s: float = 0.0) -> ModelResponse:
    choice = (data.get("choices") or [{}])[0] or {}
    msg = choice.get("message") or {}
    content: list = []
    if msg.get("reasoning_details"):
        content.append(ThinkingBlock(msg.get("reasoning") or "", provider=provider,
                                     provider_data={"reasoning_details": msg["reasoning_details"]}))
    elif msg.get("reasoning") or msg.get("reasoning_content"):
        content.append(ThinkingBlock(msg.get("reasoning") or msg.get("reasoning_content"), provider=provider))
    if msg.get("content"):
        content.append(TextBlock(msg["content"]))
    calls = msg.get("tool_calls") or []
    for i, tc in enumerate(calls):
        fn = tc.get("function") or {}
        raw = fn.get("arguments")
        args, err = _parse_args(raw)
        # why: some runtimes omit ids; make them unique across turns (call_0 every turn would collide)
        content.append(ToolUseBlock(tc.get("id") or f"call_{uuid.uuid4().hex[:8]}_{i}", fn.get("name", ""), args,
                                    raw_arguments=raw if err else None, parse_error=err, provider=provider))
    raw_stop = choice.get("finish_reason")
    if calls:
        stop = "tool_use"          # why: some runtimes say "stop" with tool calls present (Node 01 §9)
    else:
        stop = {"stop": "end_turn", "length": "max_tokens", "content_filter": "content_filter"}.get(raw_stop, "other")
    u = data.get("usage") or {}
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    usage = Usage(input_tokens=(u.get("prompt_tokens") or 0) - cached, output_tokens=u.get("completion_tokens") or 0,
                  cache_read_tokens=cached,
                  reasoning_tokens=(u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0,
                  cost_usd=u.get("cost"))
    return ModelResponse(content, stop, usage, data.get("model") or "", provider, id=data.get("id"),
                         latency_s=latency_s, raw_stop_reason=raw_stop, raw=data)


class OpenAICompatModel:
    def __init__(self, model: str, base_url: str, api_key: str | None, provider: str, client: Any = None) -> None:
        self.model, self.provider = model, provider
        self._base_url, self._api_key, self._client = base_url, api_key, client
        self.last_dropped_opts: list[str] = []

    @property
    def client(self):
        if self._client is None:
            import openai
            self._client = openai.OpenAI(base_url=self._base_url, api_key=self._api_key or "none")
        return self._client

    def complete(self, *, system: str | list[TextBlock], messages: list[Message], tools: list[ToolSpec] | None = None,
                 max_tokens: int = 1024, **opts: Any) -> ModelResponse:
        req, self.last_dropped_opts = to_openai_request(model=self.model, system=system, messages=messages, tools=tools,
                                                        max_tokens=max_tokens, opts=opts, provider=self.provider)
        t0 = time.perf_counter()
        data = self.client.chat.completions.create(**req).model_dump()
        r = from_openai_response(data, provider=self.provider, latency_s=time.perf_counter() - t0)
        r.model = r.model or self.model
        return r
