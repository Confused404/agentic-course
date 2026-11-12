"""Node 00: say hello to three models from three vendors through their *raw* SDKs, with a budget and a trace.

    .venv/bin/python nodes/00-setup/hello_providers.py            # fast, gpt-fast and local
    .venv/bin/python nodes/00-setup/hello_providers.py local      # just one alias

Which models those aliases mean depends on your keys (`make check-env` shows it): with only an OpenRouter key,
three free models, all through the OpenAI SDK; with an Anthropic key, `fast` is Claude through the Anthropic SDK.

Read this file top to bottom before running it. Notice that the two SDKs disagree on almost
everything: where the system prompt goes, what usage fields are called, where the text lives.
Node 02 is about hiding those differences behind one interface. Here you just see them.
"""
from __future__ import annotations

import sys
import time

import anthropic
import openai

from agentlab import tracing
from agentlab.config import api_key, provider_config, resolve
from agentlab.costs import Budget, BudgetExceeded
from agentlab.llm.types import Usage

PROMPT = "In one sentence: what is an agentic loop?"
budget = Budget(limit_usd=0.05, label="node00-hello")   # five cents is plenty


def hello_anthropic(model: str) -> None:
    client = anthropic.Anthropic(api_key=api_key("anthropic"))
    with tracing.chat_span("anthropic", model) as span:
        t0 = time.perf_counter()
        resp = client.messages.create(
            model=model, max_tokens=1024,                     # thinking counts toward max_tokens: leave room
            system="You are concise.",                        # Anthropic: system is a top-level field
            messages=[{"role": "user", "content": PROMPT}],
        )
        dt = time.perf_counter() - t0
        text = "".join(b.text for b in resp.content if b.type == "text")   # content is a list of blocks
        u = resp.usage
        details = getattr(u, "output_tokens_details", None)
        usage = Usage(input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                      cache_read_tokens=u.cache_read_input_tokens or 0,
                      cache_write_tokens=u.cache_creation_input_tokens or 0,
                      reasoning_tokens=getattr(details, "thinking_tokens", 0) or 0)
        cost = budget.charge(model, usage, provider="anthropic")
        tracing.record_usage(span, usage)
        span.set_attribute("gen_ai.response.model", resp.model)
        span.set_attribute("gen_ai.response.finish_reasons", [resp.stop_reason or ""])
        span.set_attribute("course.cost_usd", cost)
    print(f"[anthropic:{model}] {dt:.2f}s ${cost:.6f} stop={resp.stop_reason}")
    print(f"  raw usage: {u.model_dump(exclude_none=True)}")       # the vendor's own field names
    print(f"  {text or '(empty: did thinking use the whole max_tokens?)'}\n")


def hello_openai_compatible(provider: str, model: str) -> None:
    cfg = provider_config(provider)
    client = openai.OpenAI(base_url=cfg["base_url"], api_key=api_key(provider))
    with tracing.chat_span(provider, model) as span:
        t0 = time.perf_counter()
        resp = client.chat.completions.create(
            model=model, max_tokens=1024,       # reasoning models spend output tokens thinking first
            messages=[{"role": "system", "content": "You are concise."},   # OpenAI: system is a message
                      {"role": "user", "content": PROMPT}],
            # OpenRouter-only field asking for exact cost in usage; other servers ignore unknown body fields
            **({"extra_body": {"usage": {"include": True}}} if provider == "openrouter" else {}),
        )
        dt = time.perf_counter() - t0
        choice = resp.choices[0]                              # a list of alternatives, usually 1
        u = resp.usage
        cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        reasoning = getattr(getattr(u, "completion_tokens_details", None), "reasoning_tokens", 0) or 0
        usage = Usage(input_tokens=u.prompt_tokens - cached, output_tokens=u.completion_tokens,
                      cache_read_tokens=cached, reasoning_tokens=reasoning,
                      cost_usd=getattr(u, "cost", None))      # OpenRouter reports cost; others don't
        cost = budget.charge(model, usage, provider=provider)
        tracing.record_usage(span, usage)
        span.set_attribute("gen_ai.response.model", resp.model or model)
        span.set_attribute("gen_ai.response.finish_reasons", [choice.finish_reason or ""])
        span.set_attribute("course.cost_usd", cost)
    print(f"[{provider}:{model}] {dt:.2f}s ${cost:.6f} finish={choice.finish_reason}")
    print(f"  raw usage: {u.model_dump(exclude_none=True)}")
    print(f"  {choice.message.content or '(empty: did reasoning use the whole max_tokens?)'}\n")


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    with tracing.agent_span("node00-hello"):
        for alias in ("fast", "gpt-fast", "local"):
            if only and only != alias:
                continue
            provider, model = resolve(alias)
            if not api_key(provider):
                print(f"[{alias} = {provider}:{model}] skipped: no API key for {provider} in .env\n")
                continue
            try:
                if provider == "anthropic":
                    hello_anthropic(model)
                else:
                    hello_openai_compatible(provider, model)
            except BudgetExceeded:
                raise                # the cap is a hard stop, never "skip to the next model"
            except Exception as e:  # keep going: one broken provider shouldn't hide the others
                print(f"[{alias} = {provider}:{model}] FAILED: {type(e).__name__}: {e}\n")
    print(f"Total spent: ${budget.spent_usd:.6f} of ${budget.limit_usd:.2f}.  Now run: make trace")


if __name__ == "__main__":
    main()
