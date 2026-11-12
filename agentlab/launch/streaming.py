"""Vendor streams -> the course's streaming events (Node 17 SPEC §1; event format in stream.py).

The adapters' stream() methods (Node 02 files, extended in this node) call the vendor API with stream=True and pass
each raw event, as a plain dict, through these mappers; stream.assemble() builds the final ModelResponse.
"""
from __future__ import annotations

from typing import Any, Iterable, Iterator

from agentlab.launch import stream as stream_module

ANTHROPIC_STOPS = {"end_turn": "end_turn", "tool_use": "tool_use", "max_tokens": "max_tokens",
                   "stop_sequence": "stop_sequence", "pause_turn": "pause_turn", "refusal": "refusal"}
OPENAI_STOPS = {"stop": "end_turn", "tool_calls": "tool_use", "function_call": "tool_use", "length": "max_tokens",
                "content_filter": "refusal"}


def _d(x: Any) -> dict:
    return x if isinstance(x, dict) else (x.model_dump() if hasattr(x, "model_dump") else dict(x))


def anthropic_events(raw: Iterable[Any]) -> Iterator[dict]:
    usage: dict = {}
    stop = None
    for ev in raw:
        e = _d(ev)
        t = e.get("type")
        if t == "message_start":
            m = e.get("message") or {}
            u = m.get("usage") or {}
            usage = {"input_tokens": u.get("input_tokens") or 0,
                     "cache_read_tokens": u.get("cache_read_input_tokens") or 0,
                     "cache_write_tokens": u.get("cache_creation_input_tokens") or 0,
                     "output_tokens": u.get("output_tokens") or 0}
            yield {"type": "message_start", "id": m.get("id"), "model": m.get("model")}
        elif t == "content_block_start":
            b, i = e.get("content_block") or {}, e.get("index", 0)
            if b.get("type") == "tool_use":
                yield {"type": "tool_use_start", "index": i, "id": b.get("id"), "name": b.get("name")}
            elif b.get("type") == "text" and b.get("text"):
                yield {"type": "text_delta", "index": i, "text": b["text"]}
        elif t == "content_block_delta":
            d, i = e.get("delta") or {}, e.get("index", 0)
            if d.get("type") == "text_delta":
                yield {"type": "text_delta", "index": i, "text": d.get("text", "")}
            elif d.get("type") == "input_json_delta":
                yield {"type": "tool_input_delta", "index": i, "partial_json": d.get("partial_json", "")}
        elif t == "content_block_stop":
            yield {"type": "block_stop", "index": e.get("index", 0)}
        elif t == "message_delta":
            stop = (e.get("delta") or {}).get("stop_reason") or stop
            out = (e.get("usage") or {}).get("output_tokens")
            if out is not None:
                usage["output_tokens"] = out
        elif t == "message_stop":
            yield {"type": "message_stop", "stop_reason": ANTHROPIC_STOPS.get(stop or "", "other"), "usage": usage}


def openai_events(chunks: Iterable[Any]) -> Iterator[dict]:
    import uuid
    started, finish, usage = False, None, {}
    prefix = uuid.uuid4().hex[:8]              # why: fallback ids must not repeat across turns (Node 02's rule)
    tools: dict[int, int] = {}                 # OpenAI tool index -> course block index (text is block 0)
    saw_any = False
    for ch in chunks:
        c = _d(ch)
        saw_any = True
        if not started:
            started = True
            yield {"type": "message_start", "id": c.get("id"), "model": c.get("model")}
        for choice in c.get("choices") or []:
            d = choice.get("delta") or {}
            if d.get("content"):
                yield {"type": "text_delta", "index": 0, "text": d["content"]}
            for tc in d.get("tool_calls") or []:
                k = tc.get("index", 0)
                fn = tc.get("function") or {}
                if k not in tools:
                    tools[k] = len(tools) + 1
                    yield {"type": "tool_use_start", "index": tools[k], "id": tc.get("id") or f"call_{prefix}_{k}",
                           "name": fn.get("name") or ""}
                if fn.get("arguments"):
                    yield {"type": "tool_input_delta", "index": tools[k], "partial_json": fn["arguments"]}
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
        u = c.get("usage")
        if u:
            cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
            usage = {"input_tokens": (u.get("prompt_tokens") or 0) - cached, "cache_read_tokens": cached,
                     "output_tokens": u.get("completion_tokens") or 0, "cost_usd": u.get("cost")}
    if saw_any and finish is not None:
        # why only with a finish reason: without one the stream was cut off, and assemble() must see that.
        # Tool calls present -> "tool_use" whatever finish_reason says (some runtimes say "stop"; Node 02 does
        # the same normalisation for non-streamed responses)
        stop = "tool_use" if tools else OPENAI_STOPS.get(finish, "other")
        yield {"type": "message_stop", "stop_reason": stop, "usage": usage}


def run_stream(mapped: Iterable[dict], *, provider: str, model: str) -> Iterator[dict]:
    """Yield the mapped events, then {"type": "response", "response": assemble(...)}."""
    seen: list[dict] = []
    for e in mapped:
        seen.append(e)
        yield e
    yield {"type": "response", "response": stream_module.assemble(seen, provider=provider, model=model)}


def stream_or_complete(model: Any, **kw: Any) -> Iterator[dict]:
    """Stream if the model's class implements stream() (wrappers forwarding attributes don't count: a forwarded
    stream() would skip the wrapper's own behaviour); otherwise complete() and replay it as events."""
    if callable(getattr(type(model), "stream", None)):
        yield from model.stream(**kw)
        return
    r = model.complete(**kw)
    yield {"type": "message_start", "id": r.id, "model": r.model}
    if r.text:
        yield {"type": "text_delta", "index": 0, "text": r.text}
    yield {"type": "response", "response": r}
