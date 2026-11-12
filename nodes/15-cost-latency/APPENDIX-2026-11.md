# Appendix (dated 2026-11): cost and latency in practice

## Prices used in this node (check before relying on them)
- Claude Haiku 5.5 $0.10 / $0.50 per 1M input/output tokens (prompts up to 100K tokens; $0.50 / $2.50 above),
  Sonnet 5.5 $2 / $10, Opus 5.5 $4 / $20. OpenAI GPT-6 Luna $0.10 / $0.50 and GPT-6.1 Terra $1 / $5 on OpenAI's
  standard tier (via OpenRouter, 2026-11-04). `config/models.toml` holds the table; `make models` refreshes
  OpenRouter's. https://platform.claude.com/docs/en/about-claude/pricing · https://openrouter.ai/models

## Prompt caching
- **Anthropic**: prefix order tools → system → messages; a change invalidates its level and everything after it.
  5-minute writes cost 1.25× input, 1-hour writes 2×; reads 0.1× (0.05× on Opus 5.5 and Sonnet 5.5). Minimum
  cacheable prompt: 512 tokens on the 5.5 models (up to 4,096 on some older ones); shorter prompts just aren't
  cached, with no error. Up to 4 breakpoints; a top-level `cache_control` turns on automatic caching (its
  breakpoint follows the conversation). Changing thinking or effort settings invalidates message caches. Cache
  hits don't count against rate limits.
  https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- **Anthropic cache diagnostics**: send `diagnostics: {"previous_message_id": <last response id>}` and the
  response says where the prefix first changed (`cache_miss_reason.type`, e.g. `system_changed`) and how many
  tokens missed. It was a beta (`cache-diagnosis-2026-04-07` header) in 2026; check whether the header is still
  needed. Your `first_divergence` does the same from recorded requests, for any provider.
  https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics
- **OpenAI-style automatic caching**: prompts over ~1,024 tokens are cached automatically from the start of the
  request; cached input is billed at a discount and reported as `usage.prompt_tokens_details.cached_tokens`.
  `prompt_cache_key` helps route similar requests to the same cache.
  https://platform.openai.com/docs/guides/prompt-caching
- **Through OpenRouter**: hits depend on the request reaching the same upstream provider; OpenRouter reports
  cached tokens and charges the provider's cache prices. Free (`:free`) endpoints often don't report caching.

## Speed and price tiers
- **Batch APIs**: Anthropic's Message Batches bill everything at 50%, finish most batches within an hour (24 h at
  most), and stack with prompt caching (cache hits in batches are best-effort). OpenAI's Batch API is also 50%;
  OpenRouter lists `:batch` variants at half price.
  https://platform.claude.com/docs/en/build-with-claude/batch-processing
- **Faster output at a higher price**: Anthropic's fast mode (`speed: "fast"`) gives up to 2.5× output tokens per
  second on supported Opus models (Opus 5.5 at $8 / $40, twice standard); it raises output speed, not time to
  first token, and isn't available in batches. OpenAI offers priority processing (faster, pricier) and flex
  processing (slower, cheaper); OpenRouter shows them as separate endpoints (e.g. `openai/fast`, `openai/flex`).
  https://platform.claude.com/docs/en/build-with-claude/fast-mode

## Self-hosting
- Throughput (tokens per second) depends on the GPU, the model size and quantization, the serving engine (vLLM,
  SGLang, TGI, llama.cpp) and above all batch size: one user's request uses a fraction of what the GPU can serve
  concurrently. Measure on your own workload; elective E5 walks through it on free compute tiers.

## Check before relying on this appendix
Prices and cache multipliers (they changed several times in 2026); minimum cacheable lengths for the model you
use; whether cache diagnostics still needs a beta header; which OpenRouter endpoints report cached tokens.
