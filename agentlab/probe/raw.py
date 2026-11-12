"""Raw, timed, budgeted, traced calls to vendor SDKs. I/O only; parsing lives in parse.py.

Deliberately NOT using agentlab.llm adapters: Node 01 is about seeing each vendor's native shapes.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agentlab import tracing
from agentlab.config import api_key, provider_config
from agentlab.costs import Budget, BudgetExceeded
from agentlab.probe.parse import parse_anthropic, parse_openai
from agentlab.probe.results import ProbeResult


def _anthropic_client():
    import anthropic
    return anthropic.Anthropic(api_key=api_key("anthropic"))


def _openai_client(provider: str):
    import openai
    return openai.OpenAI(base_url=provider_config(provider)["base_url"], api_key=api_key(provider) or "none")


def _finish(result: ProbeResult, parsed: dict, budget: Budget, span) -> None:
    u = parsed["usage"]
    result.text, result.tool_calls, result.stop_reason = parsed["text"], parsed["tool_calls"], parsed["stop_reason"]
    result.input_tokens, result.output_tokens = u.input_tokens, u.output_tokens
    result.cache_read_tokens, result.cache_write_tokens = u.cache_read_tokens, u.cache_write_tokens
    result.reasoning_tokens = u.reasoning_tokens
    # why: charge AFTER the call; BudgetExceeded must stop the experiment, so we let it propagate
    result.cost_usd = budget.charge(result.model, u)
    a = tracing.ATTR
    span.set_attribute(a["in_tokens"], u.input_tokens)
    span.set_attribute(a["out_tokens"], u.output_tokens)
    span.set_attribute(a["cache_read"], u.cache_read_tokens)
    span.set_attribute(a["cache_write"], u.cache_write_tokens)
    span.set_attribute(a["finish"], [parsed["stop_reason"]])
    span.set_attribute(a["cost"], result.cost_usd)


def _save(save_raw: Path | None, request: dict, response: dict) -> None:
    if save_raw:
        save_raw = Path(save_raw)
        save_raw.parent.mkdir(parents=True, exist_ok=True)
        save_raw.write_text(json.dumps({"request": request, "response": response}, indent=2, default=str))


def anthropic_call(model: str, *, system: str | list[dict], messages: list[dict], budget: Budget,
                   experiment: str, label: str = "", tools: list[dict] | None = None, max_tokens: int = 512,
                   stream: bool = True, save_raw: Path | None = None, client: Any = None,
                   **extra: Any) -> ProbeResult:
    result = ProbeResult(experiment, "anthropic", model, label=label, params=dict(extra))
    request: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "system": system, "messages": messages,
                               **extra}
    if tools:
        request["tools"] = tools
    with tracing.chat_span("anthropic", model) as span:
        t0 = time.perf_counter()
        try:
            client = client or _anthropic_client()
            if stream:
                with client.messages.stream(**request) as s:
                    for event in s:
                        if getattr(event, "type", "") != "content_block_delta":
                            continue
                        now = time.perf_counter() - t0
                        # why: for reasoning models, visible TTFT includes thinking time (TEXTBOOK §3), so we
                        # record both "first delta of any kind" and "first visible text/tool delta"
                        result.extra.setdefault("ttft_any_s", now)
                        kind = getattr(getattr(event, "delta", None), "type", "")
                        if result.ttft_s is None and kind in ("text_delta", "input_json_delta"):
                            result.ttft_s = now
                    final = s.get_final_message().model_dump()
            else:
                final = client.messages.create(**request).model_dump()
            result.total_s = time.perf_counter() - t0
            result.extra.update({"message_id": final.get("id"), "raw_stop_reason": final.get("stop_reason")})
            if final.get("diagnostics") is not None:
                result.extra["diagnostics"] = final["diagnostics"]
            _save(save_raw, request, final)
            _finish(result, parse_anthropic(final), budget, span)
        except BudgetExceeded:
            raise
        except Exception as e:  # noqa: BLE001 - experiments record failures and keep going
            result.total_s = time.perf_counter() - t0
            result.error = f"{type(e).__name__}: {e}"
    return result


def anthropic_count_tokens(model: str, *, system: str | list[dict], messages: list[dict],
                           tools: list[dict] | None = None, client: Any = None) -> int:
    client = client or _anthropic_client()
    kw: dict[str, Any] = {"model": model, "messages": messages}
    if system:
        kw["system"] = system
    if tools:
        kw["tools"] = tools
    return client.messages.count_tokens(**kw).input_tokens


def _rebuild_from_stream(chunks_iter, t0: float, result: ProbeResult) -> dict:
    """Reassemble a Chat Completions response from stream chunks (TEXTBOOK §9: arguments arrive in pieces)."""
    content, calls, finish, usage, model, rid = [], {}, None, None, "", None
    for chunk in chunks_iter:
        c = chunk.model_dump() if hasattr(chunk, "model_dump") else chunk
        model, rid = c.get("model") or model, c.get("id") or rid
        if c.get("usage"):
            usage = c["usage"]
        for ch in c.get("choices") or []:
            delta = ch.get("delta") or {}
            if delta.get("content") or delta.get("tool_calls") or delta.get("reasoning") or delta.get("reasoning_content"):
                result.extra.setdefault("ttft_any_s", time.perf_counter() - t0)
            if result.ttft_s is None and (delta.get("content") or delta.get("tool_calls")):
                result.ttft_s = time.perf_counter() - t0
            if delta.get("content"):
                content.append(delta["content"])
            for tc in delta.get("tool_calls") or []:
                slot = calls.setdefault(tc.get("index", 0), {"id": None, "type": "function",
                                                            "function": {"name": None, "arguments": ""}})
                slot["id"] = tc.get("id") or slot["id"]
                fn = tc.get("function") or {}
                slot["function"]["name"] = fn.get("name") or slot["function"]["name"]
                slot["function"]["arguments"] += fn.get("arguments") or ""
            finish = ch.get("finish_reason") or finish
    msg: dict[str, Any] = {"role": "assistant", "content": "".join(content) or None}
    if calls:
        msg["tool_calls"] = [calls[i] for i in sorted(calls)]
    if usage is None:
        result.extra["usage_missing"] = True
    return {"id": rid, "object": "chat.completion", "model": model,
            "choices": [{"index": 0, "finish_reason": finish, "message": msg}], "usage": usage}


def openai_compat_call(provider: str, model: str, *, system: str, messages: list[dict], budget: Budget,
                       experiment: str, label: str = "", tools: list[dict] | None = None, max_tokens: int = 512,
                       stream: bool = True, save_raw: Path | None = None, client: Any = None,
                       **extra: Any) -> ProbeResult:
    result = ProbeResult(experiment, provider, model, label=label, params=dict(extra))
    # why: OpenAI puts the system prompt in the message list (TEXTBOOK §9)
    request: dict[str, Any] = {"model": model, "max_tokens": max_tokens,
                               "messages": [{"role": "system", "content": system}, *messages], **extra}
    if tools:
        request["tools"] = tools
    with tracing.chat_span(provider, model) as span:
        t0 = time.perf_counter()
        try:
            client = client or _openai_client(provider)
            if stream:
                chunks = client.chat.completions.create(**request, stream=True,
                                                        stream_options={"include_usage": True})
                final = _rebuild_from_stream(chunks, t0, result)
            else:
                final = client.chat.completions.create(**request).model_dump()
            result.total_s = time.perf_counter() - t0
            first = (final.get("choices") or [{}])[0] or {}
            result.extra.update({"message_id": final.get("id"), "raw_stop_reason": first.get("finish_reason")})
            _save(save_raw, request, final)
            _finish(result, parse_openai(final), budget, span)
        except BudgetExceeded:
            raise
        except Exception as e:  # noqa: BLE001
            result.total_s = time.perf_counter() - t0
            result.error = f"{type(e).__name__}: {e}"
    return result
