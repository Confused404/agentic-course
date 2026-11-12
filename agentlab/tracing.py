"""Tracing with OpenTelemetry, using the GenAI semantic conventions.

Every agent run produces a tree of spans:  invoke_agent -> chat (one per model call)
                                                         -> execute_tool (one per tool call)
By default spans are written as JSON lines to runs/traces/<trace_id>.jsonl, readable offline with
`make trace` (scripts/trace_view.py). If OTEL_EXPORTER_OTLP_ENDPOINT is set and the `otlp` extra is
installed, spans are ALSO sent to a collector (Phoenix, Jaeger, Langfuse...). See nodes/00-setup.

STABILITY WARNING (checked 2026-11-04): the gen_ai.* attribute names are at "Development"
stability, and the GenAI conventions have moved out of the main semantic-conventions repo into
open-telemetry/semantic-conventions-genai. Names can change without notice. All names used by the
course live in the ATTR dict below so a rename is a one-line change. See nodes/14-reliability APPENDIX.

Token accounting: gen_ai.usage.input_tokens records ALL prompt tokens (cached included), and the
cache_read / cache_creation attributes break that total down. Our Usage dataclass stores uncached
input separately (for pricing), so record_response() adds them back up.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

import agentlab.config as cfg

ATTR = {
    "op": "gen_ai.operation.name",            # chat | invoke_agent | execute_tool
    "provider": "gen_ai.provider.name",       # anthropic | openai | ...
    "req_model": "gen_ai.request.model",
    "resp_model": "gen_ai.response.model",
    "finish": "gen_ai.response.finish_reasons",
    "in_tokens": "gen_ai.usage.input_tokens",          # total prompt tokens incl. cached
    "out_tokens": "gen_ai.usage.output_tokens",
    "cache_read": "gen_ai.usage.cache_read.input_tokens",
    "cache_write": "gen_ai.usage.cache_creation.input_tokens",
    "reasoning": "gen_ai.usage.reasoning.output_tokens",
    "resp_id": "gen_ai.response.id",
    "agent": "gen_ai.agent.name",
    "tool": "gen_ai.tool.name",
    "tool_call_id": "gen_ai.tool.call.id",
    # course-specific (not part of the convention; prefixed to make that obvious)
    "cost": "course.cost_usd",
    "uncached_in": "course.usage.uncached_input_tokens",
    "tool_args": "course.tool.arguments",
    "tool_result": "course.tool.result",
    "tool_error": "course.tool.is_error",
    "content": "course.content",              # only recorded when TRACE_CONTENT=1 (privacy!)
}

TRACE_CONTENT = os.environ.get("TRACE_CONTENT", "1") == "1"   # course default: on (it is your data)


class JsonlExporter(SpanExporter):
    def export(self, spans: list[ReadableSpan]) -> SpanExportResult:
        d = cfg.RUNS / "traces"   # read at export time so tests can redirect it
        d.mkdir(parents=True, exist_ok=True)
        for s in spans:
            rec = {
                "trace_id": f"{s.context.trace_id:032x}", "span_id": f"{s.context.span_id:016x}",
                "parent_id": f"{s.parent.span_id:016x}" if s.parent else None,
                "name": s.name, "start": s.start_time, "end": s.end_time,
                "status": s.status.status_code.name, "attributes": dict(s.attributes or {}),
                "events": [{"name": e.name, "attributes": dict(e.attributes or {})} for e in s.events],
            }
            with open(d / f"{rec['trace_id']}.jsonl", "a") as f:
                f.write(json.dumps(rec, default=str) + "\n")
        return SpanExportResult.SUCCESS


_configured = False


def setup(service_name: str = "agentlab") -> trace.Tracer:
    global _configured
    if not _configured:
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_span_processor(SimpleSpanProcessor(JsonlExporter()))
        if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                from opentelemetry.sdk.trace.export import BatchSpanProcessor
                provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            except ImportError:
                print("OTEL_EXPORTER_OTLP_ENDPOINT set but `otlp` extra not installed; JSONL only.")
        # note: the OTLP exporter appends /v1/traces to OTEL_EXPORTER_OTLP_ENDPOINT itself, so set the
        # base URL (http://localhost:6006), or set OTEL_EXPORTER_OTLP_TRACES_ENDPOINT to the full URL.
        trace.set_tracer_provider(provider)
        _configured = True
    return trace.get_tracer("agentlab")


def _short(v: Any, n: int = 4000) -> str:
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    return s if len(s) <= n else s[:n] + f"...[{len(s) - n} more chars]"


@contextmanager
def agent_span(agent_name: str, **attrs: Any) -> Iterator[trace.Span]:
    with setup().start_as_current_span(f"invoke_agent {agent_name}") as span:
        span.set_attribute(ATTR["op"], "invoke_agent")
        span.set_attribute(ATTR["agent"], agent_name)
        for k, v in attrs.items():
            span.set_attribute(f"course.{k}", _short(v) if not isinstance(v, (int, float, bool)) else v)
        yield span


@contextmanager
def chat_span(provider: str, model: str) -> Iterator[trace.Span]:
    with setup().start_as_current_span(f"chat {model}") as span:
        span.set_attribute(ATTR["op"], "chat")
        span.set_attribute(ATTR["provider"], provider)
        span.set_attribute(ATTR["req_model"], model)
        yield span


def record_response(span: trace.Span, resp: Any, cost: float | None) -> None:
    """Call inside chat_span after the model returns (resp is a ModelResponse)."""
    span.set_attribute(ATTR["resp_model"], resp.model)
    span.set_attribute(ATTR["finish"], [resp.stop_reason])
    record_usage(span, resp.usage)
    if resp.id:
        span.set_attribute(ATTR["resp_id"], resp.id)
    if cost is not None:
        span.set_attribute(ATTR["cost"], cost)
    if TRACE_CONTENT:
        span.set_attribute(ATTR["content"], _short([b.__dict__ for b in resp.content]))


def record_usage(span: trace.Span, usage: Any) -> None:
    """Set token attributes from a Usage. input_tokens = total prompt tokens (see module docstring)."""
    span.set_attribute(ATTR["in_tokens"], usage.total_input)
    span.set_attribute(ATTR["uncached_in"], usage.input_tokens)
    span.set_attribute(ATTR["out_tokens"], usage.output_tokens)
    span.set_attribute(ATTR["cache_read"], usage.cache_read_tokens)
    span.set_attribute(ATTR["cache_write"], usage.cache_write_tokens)
    if usage.reasoning_tokens:
        span.set_attribute(ATTR["reasoning"], usage.reasoning_tokens)


@contextmanager
def tool_span(name: str, call_id: str, args: dict) -> Iterator[trace.Span]:
    with setup().start_as_current_span(f"execute_tool {name}") as span:
        span.set_attribute(ATTR["op"], "execute_tool")
        span.set_attribute(ATTR["tool"], name)
        span.set_attribute(ATTR["tool_call_id"], call_id)
        if TRACE_CONTENT:
            span.set_attribute(ATTR["tool_args"], _short(args))
        yield span


def record_tool_result(span: trace.Span, result: str, is_error: bool) -> None:
    span.set_attribute(ATTR["tool_error"], is_error)
    if TRACE_CONTENT:
        span.set_attribute(ATTR["tool_result"], _short(result))


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return f"{ctx.trace_id:032x}" if ctx.is_valid else None
