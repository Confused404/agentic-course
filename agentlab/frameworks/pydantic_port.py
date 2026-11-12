"""The support assistant on Pydantic AI (Node 16 TEXTBOOK §3).

Same prompt, same Shopfront tools, same budget; Pydantic AI runs the loop and talks to the provider. The class at the
bottom speaks the Node 04 eval contract (chat() -> .reply/.result, .transcript, .turn_stats), so the same graders
score both implementations.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import Agent, DeferredToolRequests, Tool, UsageLimits
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.models.wrapper import WrapperModel

from agentlab import tracing
from agentlab.assistant.prompts import get_prompt
from agentlab.assistant.tools import make_support_tools
from agentlab.config import api_key, fallbacks_for, is_free_model, models_config, provider_config, resolve
from agentlab.costs import Budget
from agentlab.frameworks import convert as convert_module
from agentlab.llm.types import Message, ToolUseBlock, Usage
from shopfront import clock


class PacedModel(WrapperModel):
    """OpenRouter free models: share the course's process-wide pacing (agentlab/llm/pacing.py), which Pydantic AI's
    own HTTP client knows nothing about."""

    async def request(self, messages, model_settings, model_request_parameters):
        from agentlab.llm import pacing
        rpm = models_config().get("free_tier", {}).get("requests_per_minute", 18)
        await asyncio.to_thread(pacing._wait_for_slot, rpm, time.monotonic, time.sleep)
        return await super().request(messages, model_settings, model_request_parameters)


def pai_model(alias: str):
    """A Pydantic AI model for one of the course's aliases (same provider, same model id)."""
    provider, model = resolve(alias)
    if provider == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider
        return AnthropicModel(model, provider=AnthropicProvider(api_key=api_key("anthropic")))
    if provider == "openrouter":
        from pydantic_ai.models.fallback import FallbackModel
        from pydantic_ai.models.openrouter import OpenRouterModel
        from pydantic_ai.providers.openrouter import OpenRouterProvider
        prov = OpenRouterProvider(api_key=api_key("openrouter"))
        ids = [model, *fallbacks_for(model)]
        models = [OpenRouterModel(m, provider=prov) for m in ids]
        if is_free_model(provider, model):
            models = [PacedModel(m) for m in models]
        # why client-side: Pydantic AI's FallbackModel is the framework's own answer to the course's [fallbacks]
        return models[0] if len(models) == 1 else FallbackModel(*models)
    if provider in ("ollama", "openai"):
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider
        cfg = provider_config(provider)
        return OpenAIChatModel(model, provider=OpenAIProvider(base_url=cfg["base_url"],
                                                              api_key=api_key(provider) or "none"))
    raise ValueError(f"no Pydantic AI mapping for provider {provider!r}")


def pai_tools(registry) -> list[Tool]:
    """Course tools as Pydantic AI tools, schema and all. A business error is raised as ToolFailed: Pydantic AI
    then sends the model a FAILED tool result (is_error, like the course loop), without spending a retry.
    sequential=True: Pydantic AI would otherwise run sync tools of one response concurrently in worker threads,
    out of order, on one shared SQLite connection; the course loop runs them in call order."""
    from pydantic_ai.exceptions import ToolFailed

    def make(name: str) -> Tool:
        spec = registry.get(name)
        counter = {"n": 0}

        def fn(**kwargs: Any) -> str:
            counter["n"] += 1
            r = registry.execute(ToolUseBlock(f"pai_{name}_{counter['n']}", name, kwargs))
            if r.is_error:
                raise ToolFailed(r.text)
            return r.text
        return Tool.from_schema(fn, name=spec.name, description=spec.description, json_schema=spec.input_schema,
                                sequential=True)
    return [make(n) for n in registry.names()]


MODEL_SETTINGS = {"max_tokens": 2048}      # same as the course loop / the graph port (Pydantic AI's default is larger)


def build_agent(model, registry, system: str, *, approval_tools: frozenset[str] = frozenset()) -> Agent:
    tools = pai_tools(registry)
    if approval_tools:
        for t in tools:
            if t.name in approval_tools:
                t.requires_approval = True
        return Agent(model, instructions=system, tools=tools, output_type=[str, DeferredToolRequests],
                     model_settings=MODEL_SETTINGS)
    return Agent(model, instructions=system, tools=tools, model_settings=MODEL_SETTINGS)


def course_usage(u, provider_details: dict | None = None) -> Usage:
    """Pydantic AI's input_tokens INCLUDE cache reads/writes; the course's input_tokens are the uncached part.
    Cost: only what the PROVIDER reported (OpenRouter puts it in provider_details["cost"]). Pydantic AI's own
    `usage.cost` is an estimate from its bundled price data, not the course's price table: ignored."""
    cr, cw = getattr(u, "cache_read_tokens", 0) or 0, getattr(u, "cache_write_tokens", 0) or 0
    reported = (provider_details or {}).get("cost")
    return Usage(input_tokens=max(0, (u.input_tokens or 0) - cr - cw), output_tokens=u.output_tokens or 0,
                 cache_read_tokens=cr, cache_write_tokens=cw,
                 reasoning_tokens=getattr(u, "output_reasoning_tokens", 0) or 0,
                 cost_usd=float(reported) if reported is not None else None)


class BudgetedModel(WrapperModel):
    """Budget check before, charge after EVERY request, plus a trace span: the same guarantees as the course loop
    (a run that fails half-way has still paid for what it used)."""

    def __init__(self, wrapped, budget: Budget | None, price_model: str, provider: str | None) -> None:
        super().__init__(wrapped)
        self.budget, self.price_model, self.course_provider = budget, price_model, provider
        self.responses = 0
        self.usage = Usage()
        self.cost = 0.0

    async def request(self, messages, model_settings, model_request_parameters):
        if self.budget is not None:
            self.budget.check()
        with tracing.chat_span(self.course_provider or "pydantic-ai", self.price_model) as span:
            resp = await super().request(messages, model_settings, model_request_parameters)
            u = course_usage(resp.usage, resp.provider_details)
            tracing.record_usage(span, u)
        self.responses += 1
        self.usage = self.usage + u
        if self.budget is not None:
            self.cost += self.budget.charge(self.price_model, u, provider=self.course_provider)
        return resp


@dataclass
class PortResult:                       # the parts of Node 02's LoopResult the eval runner reads
    stop: str
    turns: int
    usage: Usage = field(default_factory=Usage)
    cost_usd: float = 0.0
    final_text: str = ""


@dataclass
class PortReply:
    reply: str
    result: PortResult


FALLBACK_REPLY = "Sorry, I couldn't finish that. A colleague will follow up."


class PydanticSupportAssistant:
    """Node 04's eval contract on Pydantic AI."""

    def __init__(self, model, conn, customer_id: int, budget: Budget | None = None, *, max_requests: int = 8,
                 system_prompt: str | None = None, tool_variant: str = "v2", price_model: str | None = None,
                 provider: str | None = None) -> None:
        self.max_requests = max_requests
        self.system = (system_prompt or get_prompt("v2")).format(today=clock.now().date().isoformat())
        self.registry = make_support_tools(conn, customer_id, actor="agent:pydantic-ai", variant=tool_variant)
        self.model = BudgetedModel(model, budget, price_model or getattr(model, "model_name", "unknown"), provider)
        self.agent = build_agent(self.model, self.registry, self.system)
        self.history: list = []                       # Pydantic AI messages (the framework's own state)
        self.transcript: list[Message] = []           # the same conversation in course format (what graders read)
        self.turn_stats: list[dict] = []
        self.fixed_tokens: dict = {}

    def chat(self, user_text: str) -> PortReply:
        from pydantic_ai import capture_run_messages
        stop, text = "end_turn", ""
        old = list(self.history)
        n0, usage0, cost0 = self.model.responses, self.model.usage, self.model.cost
        captured: list = []
        try:
            with tracing.agent_span("support-chat-pydantic-ai") as span, capture_run_messages() as captured:
                try:
                    run = self.agent.run_sync(user_text, message_history=old,
                                              usage_limits=UsageLimits(request_limit=self.max_requests))
                    text = run.output if isinstance(run.output, str) else ""
                except UsageLimitExceeded:
                    stop = "max_turns"     # the course's name for "hit the call cap before answering"
                span.set_attribute("course.stop", stop)
        finally:
            # why finally: even a failed run (provider error, budget) keeps the conversation it had so far
            new = list(captured)[len(old):]
            self.history = old + new
            converted = convert_module.to_course_messages(new)
            if not converted or converted[0].role != "user":
                converted = [Message.user(user_text)] + converted
            self.transcript += converted
            u = Usage(input_tokens=self.model.usage.input_tokens - usage0.input_tokens,
                      output_tokens=self.model.usage.output_tokens - usage0.output_tokens,
                      cache_read_tokens=self.model.usage.cache_read_tokens - usage0.cache_read_tokens,
                      cache_write_tokens=self.model.usage.cache_write_tokens - usage0.cache_write_tokens)
            self.turn_stats.append({"turn": len(self.turn_stats) + 1, "calls": self.model.responses - n0,
                                    "input_tokens": u.total_input, "cache_read_tokens": u.cache_read_tokens,
                                    "output_tokens": u.output_tokens, "action": "none"})
        reply = text.strip() if stop == "end_turn" and text.strip() else FALLBACK_REPLY
        return PortReply(reply, PortResult(stop, self.model.responses - n0, u, self.model.cost - cost0, text))


def dump_history(history: list) -> str:
    """Pydantic AI's own serialisation: this is what you'd persist to resume a conversation (TEXTBOOK §5)."""
    from pydantic_ai import ModelMessagesTypeAdapter
    return ModelMessagesTypeAdapter.dump_json(history).decode()


def load_history(blob: str) -> list:
    from pydantic_ai import ModelMessagesTypeAdapter
    return ModelMessagesTypeAdapter.validate_json(blob)


