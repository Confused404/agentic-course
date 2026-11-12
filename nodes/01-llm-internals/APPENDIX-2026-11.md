# Appendix (dated 2026-11-04): version-specific facts Node 01 relies on

Re-check these if an experiment errors. The TEXTBOOK's mechanisms don't depend on them.

## Anthropic Messages API (SDK `anthropic==2.4.0`)
- `messages.create` parameters include: `system`, `messages`, `tools`, `tool_choice`, `max_tokens`,
  `stop_sequences`, `thinking`, `output_config`, `cache_control` (top level), `diagnostics`, `service_tier`,
  `speed`. **No `temperature`, `top_p` or `top_k`.**
- `output_config.effort`: `"low" | "medium" | "high" | "xhigh" | "max"`. Default effort differs by model
  (reported: Sonnet 5.5 defaults to high, Opus 5.5 and Haiku 5.5 to medium; secondary source, verify on the
  models page).
- `output_config.format`: `{"type": "json_schema", "schema": {...}}` for structured outputs.
- `thinking`: `{"type": "adaptive"}`, `{"type": "enabled", "budget_tokens": N, "display": "summarized"|"omitted"}`
  (N ≥ 1024; the SDK marks `enabled` deprecated on some models in favour of `adaptive`), `{"type": "between_tools"}`,
  or disabled. Which types each model accepts varies.
- `stop_reason` values: `end_turn`, `tool_use`, `max_tokens`, `stop_sequence`, `pause_turn`, `refusal`,
  `model_context_window_exceeded`.
- Thinking tokens are reported in `usage.output_tokens_details.thinking_tokens` (and billed as output).
- Caching: per-block `cache_control: {"type": "ephemeral"}`, or top-level `cache_control` to mark the last
  cacheable block automatically. Usage reports `cache_creation_input_tokens` and `cache_read_input_tokens`.
  `diagnostics: {"previous_message_id": "<id>"}` returns `diagnostics.cache_miss_reason` (types seen in the SDK:
  messages changed, model changed, system changed, tools changed, previous message not found, unavailable).
  Only requests that **include** `diagnostics` store a fingerprint, so opt in on every request (the first with
  `previous_message_id: null`). Response values: `diagnostics: null` = no divergence (or first request);
  `{"cache_miss_reason": null}` = comparison still pending; a typed reason = why it missed.
  `max_tokens: 0` pre-warms the cache without generating.
- `messages.count_tokens` counts input tokens for a would-be request.
- Prices (per 1M tokens): Haiku 5.5 $0.10 in / $0.50 out for prompts ≤ 100K tokens ($0.50 / $2.50 above);
  cache read $0.01 (≤100K). Sonnet 5.5 $2 / $10, cache read $0.10. Opus 5.5 $4 / $20, cache read $0.20.

## OpenAI-compatible Chat Completions (SDK `openai==3.45.0`)
- Accepts `temperature`, `top_p`, `seed`, `logprobs`, `top_logprobs`, `reasoning_effort`, `response_format`,
  `parallel_tool_calls`, `prompt_cache_key`, `stream_options={"include_usage": True}`. Accepting is not honouring:
  OpenAI's reasoning models ignore or reject `temperature`.
- `reasoning_effort` values in this SDK: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max` (models support subsets).
- `max_tokens` is deprecated in favour of `max_completion_tokens` on OpenAI's own API (reasoning models require the
  latter). The course sends `max_tokens` because OpenRouter and Ollama accept it; switch if you call OpenAI directly.
- OpenRouter extras (sent via `extra_body`): `{"reasoning": {"effort": "low"}}` (unified reasoning control),
  `{"provider": {"require_parameters": true}}` (route only to hosts supporting every parameter you sent),
  `{"usage": {"include": true}}` (exact cost in `usage.cost`). Reasoning state between tool turns is exposed
  as `reasoning_details`.
- Cached tokens: `usage.prompt_tokens_details.cached_tokens`. Reasoning: `usage.completion_tokens_details.reasoning_tokens`.
- OpenRouter adds `usage.cost` (USD) to responses. Prices refresh with `make models`.
- OpenAI's newer **Responses API** uses an item-based format. The course uses Chat Completions because every
  OpenAI-compatible host supports it.

## Ollama
- OpenAI-compatible endpoint at `http://localhost:11434/v1`. Some request fields are ignored.
- Default context length depends on VRAM (as of this date): **4,096** tokens under 24 GiB, **32,768** at 24–48 GiB,
  **262,144** at 48 GiB+. Override with `OLLAMA_CONTEXT_LENGTH` on the server (or per model). Over-long prompts
  are **truncated without an error**. E2 caps local inputs at 3,000 tokens by default for this reason.
- Qwen3 models think by default; their reasoning counts against `max_tokens`.
- Tool calling quality depends on the model's chat template in your Ollama version. Upgrade Ollama before
  concluding a model "can't do tools".
