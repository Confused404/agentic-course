# Appendix (dated 2026-11-04): version-specific setup details

Re-check these when something breaks. Everything else in Node 00 should stay true.

## Pinned versions
anthropic 2.4.0 · openai 3.45.0 · opentelemetry-sdk 1.45.2 · fastapi 0.162.0 · pytest 9.2.0 ·
sqlite-vec 0.1.9 · fastembed 0.9.1 · mcp 2.3.0 · pydantic-ai 2.65.0 · langgraph 1.2.19

## Model aliases (config/models.toml)
Which column applies is decided by your keys (`make check-env` prints it; `config/models.toml` explains the modes).

| Alias | free (only an OpenRouter key) | direct (with ANTHROPIC_API_KEY) | Price in/out per 1M tokens (paid) |
|---|---|---|---|
| fast | nvidia/nemotron-3.5-super-vl:free | anthropic:claude-haiku-5-5 | $0.10 / $0.50 (≤100K-token prompts; $0.50 / $2.50 above) |
| mid | nvidia/nemotron-3.5-super-vl:free | anthropic:claude-sonnet-5-5 | $2 / $10 |
| top | nvidia/nemotron-3.5-super-vl:free | anthropic:claude-opus-5-5 | $4 / $20 |
| gpt-fast | xingchen-agi/xing4.0-29b-a4b:free | openrouter:openai/gpt-6-luna | $0.10 / $0.50 |
| gpt-mid | google/gemma-4-31b-it:free | openrouter:openai/gpt-6.1-terra | $1 / $5 |
| open-hosted | google/gemma-4-31b-it:free | openrouter:qwen/qwen3.6-27b | from $0.20 / $1.40 (host-dependent) |
| local | google/gemma-4-31b-it:free | (same) | free |
| ollama | ollama:qwen3:8b (opt-in) | (same) | free (your hardware) |

In `openrouter` mode (`COURSE_MODELS=openrouter`), fast/mid/top are the same Claude models through OpenRouter
(`anthropic/claude-haiku-5.5` etc.) at the same prices. Every free model listed supported tool calling on
OpenRouter on 2026-11-04; free models rotate, so `make models` re-checks them. Free models are $0 but limited to
20 requests/minute and 50/day per account (1,000/day after $10 of credits, bought once).

## Notable API facts as of this date
- The Anthropic Messages API (SDK 2.4.0) **does not accept `temperature` / `top_p`** for current models.
  Control comes from `output_config.effort` (`low`…`max`) and `thinking` (`adaptive`, `enabled`,
  `between_tools`, `disabled`). Node 01 explores what that means.
- Thinking/reasoning tokens count toward `max_tokens` on every vendor. A tiny `max_tokens` can return
  empty text. `hello_providers.py` uses 1024 for that reason.
- OpenRouter: the script sends `extra_body={"usage": {"include": True}}` so the response carries exact
  `usage.cost`. If cost still shows as missing, the course falls back to `config/models.toml` prices.
- Anthropic supports top-level automatic `cache_control` and a `diagnostics.previous_message_id` request
  field that returns a `cache_miss_reason`. Node 15 explains both.
- OpenAI-compatible Chat Completions (OpenRouter, Ollama) still accept `temperature`, `top_p`, `seed`,
  `logprobs`. Ollama and some hosts ignore some of them silently.

## OpenCode + Ollama
OpenCode reads provider config from `opencode.json` in the project root. A minimal local-model setup:
```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama (local)",
      "options": { "baseURL": "http://localhost:11434/v1" },
      "models": { "qwen3:8b": { "name": "Qwen3 8B" } }
    }
  }
}
```
If OpenCode's config schema has changed, `opencode --help` and the schema URL above are the
places to check. Commit `opencode.json` only if it has no secrets (keys come from `opencode auth login`,
not the file).

Two cautions for local models as coding agents:
- A coding agent's system prompt plus tool definitions can be 10K+ tokens. On machines with less than
  24 GB of VRAM, Ollama's default context window (4,096 tokens as of this date; it scales up with
  VRAM) **silently truncates** it. Set `OLLAMA_CONTEXT_LENGTH=32768` before `ollama serve`.
- Small local models are weak coding agents. Use them to feel the difference, not as your daily driver.
