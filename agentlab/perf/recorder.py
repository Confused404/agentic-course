"""GIVEN: record every model call a run makes (Node 15 TEXTBOOK §2, §6).

RecordingModel wraps any ChatModel and appends one record per complete() call to a shared list. Records are plain
JSON-serialisable dicts, so a bench can save them and the cache doctor can re-read them later:

  {"seq": 0, "label": "fast", "t_start": 12.3, "latency_s": 1.42,      # label: whatever the caller named it
   "provider": "anthropic", "model": "claude-haiku-5-5",        # the model asked (after the call; a router may switch)
   "answered_by": "claude-haiku-5-5",      # the model id in the response (differs when a provider-side fallback answered)
   "wait_s": 0.0,                          # time spent waiting for a free-tier rate-limit slot (included in latency_s)
   "request": {"system": "..." | [{"text": "...", "cache": true}], "tools": [{"name","description","input_schema"}],
               "messages": [message dicts], "max_tokens": 1024, "opts": {...}},
   "usage": {"input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens",
             "cost_usd"},
   "stop_reason": "tool_use", "error": null}

A call that raises is recorded too (with "error" set and no usage), then the exception propagates.
"""
from __future__ import annotations

import time
from typing import Any

from agentlab.llm.types import TextBlock, to_dict


def request_dict(system: Any, tools: Any, messages: Any, max_tokens: int, opts: dict) -> dict:
    sys_ = system if isinstance(system, str) else [{"text": b.text, "cache": bool(getattr(b, "cache", False))}
                                                   for b in system if isinstance(b, TextBlock)]
    return {"system": sys_, "tools": [dict(t.__dict__) for t in (tools or [])],
            "messages": [to_dict(m) for m in messages], "max_tokens": max_tokens,
            "opts": {k: v for k, v in opts.items() if isinstance(v, (str, int, float, bool, list, dict, type(None)))}}


class RecordingModel:
    def __init__(self, inner: Any, sink: list[dict] | None = None, *, label: str = "", clock=time.perf_counter) -> None:
        self.inner, self.records, self.label = inner, (sink if sink is not None else []), label
        self._clock = clock

    @property
    def provider(self) -> str:
        return self.inner.provider

    @property
    def model(self) -> str:
        return self.inner.model

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def complete(self, *, system, messages, tools=None, max_tokens: int = 1024, **opts):
        rec: dict[str, Any] = {"seq": len(self.records), "label": self.label, "t_start": self._clock(),
                               "request": request_dict(system, tools, messages, max_tokens, opts)}
        try:
            r = self.inner.complete(system=system, messages=messages, tools=tools, max_tokens=max_tokens, **opts)
        except Exception as e:
            rec.update(latency_s=self._clock() - rec["t_start"], provider=self.inner.provider,
                       model=self.inner.model, usage=None, stop_reason=None, error=f"{type(e).__name__}: {e}")
            self.records.append(rec)
            raise
        rec.update(latency_s=self._clock() - rec["t_start"], provider=self.inner.provider, model=self.inner.model,
                   answered_by=getattr(r, "model", "") or self.inner.model,
                   wait_s=float(getattr(self.inner, "last_wait_s", 0.0) or 0.0),
                   usage=dict(r.usage.__dict__), stop_reason=r.stop_reason, error=None)
        self.records.append(rec)
        return r
