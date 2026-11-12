"""get_model("fast") -> a ChatModel. One place maps aliases/providers to adapter classes.

On `main` the adapters do not exist yet: you write them in Node 02. Until then this raises a
helpful error. Node 01 experiments call vendor SDKs directly on purpose, so you see the raw wire
formats before you hide them behind an abstraction.
"""
from __future__ import annotations

from agentlab.config import api_key, fallbacks_for, is_free_model, models_config, provider_config, resolve
from agentlab.llm.types import ChatModel

OPENAI_COMPATIBLE = {"openrouter", "ollama", "openai"}


def get_model(alias_or_spec: str) -> ChatModel:
    provider, model = resolve(alias_or_spec)
    try:
        if provider == "anthropic":
            from agentlab.llm.anthropic_adapter import AnthropicModel
            return AnthropicModel(model=model, api_key=api_key("anthropic"))
        if provider in OPENAI_COMPATIBLE or provider_config(provider).get("base_url"):
            # why the second test: any [providers.<name>] with a base_url speaks the OpenAI-compatible API
            # (a self-hosted vLLM/Ollama endpoint: elective E5)
            from agentlab.llm.openai_compat import OpenAICompatModel
            cfg = provider_config(provider)
            m = OpenAICompatModel(model=model, base_url=cfg["base_url"], api_key=api_key(provider),
                                  provider=provider)
            return _wrap(m, provider, model)
    except ImportError as e:
        raise NotImplementedError(
            f"No adapter for provider {provider!r} yet ({e}). You build adapters in nodes/02-agent-loop.") from e
    raise ValueError(f"Unknown provider {provider!r}")


def _wrap(m: ChatModel, provider: str, model: str) -> ChatModel:
    """Free-tier pacing and OpenRouter fallbacks (agentlab/llm/pacing.py). Only for OpenRouter: other providers
    don't understand `fallback_models`."""
    if provider != "openrouter":
        return m
    from agentlab.llm.pacing import FreeTierPacer, WithDefaults
    fb = fallbacks_for(model)
    if fb:
        m = WithDefaults(m, fallback_models=fb)
    if is_free_model(provider, model):
        m = FreeTierPacer(m, rpm=models_config().get("free_tier", {}).get("requests_per_minute", 18))
    return m
