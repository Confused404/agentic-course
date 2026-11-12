# Appendix (dated 2026-11): structured outputs and batch processing

## Structured outputs
- **Anthropic**: `output_config.format` with a JSON schema constrains the response; strict tool schemas
  (`strict: true`) constrain tool arguments. The course adapter maps `json_schema=...` to it (Node 02).
- **OpenAI / OpenRouter**: `response_format={"type": "json_schema", "json_schema": {..., "strict": true}}`. On
  OpenRouter, add `provider.require_parameters=true` so the request only goes to hosts that support it; otherwise a
  host may ignore the schema silently.
- **Local / open models**: Ollama supports a `format` JSON schema; vLLM and llama.cpp support grammar-constrained
  decoding. Support for `strict` varies: always validate.

## Sampling for votes
Anthropic's current models don't take `temperature`/`top_p` in the course SDK version (Node 01): votes rely on the
default sampling. OpenAI-compatible models accept `temperature`; raising it increases vote diversity (and
disagreement). Some APIs return several samples in one call (`n`), which is cheaper on input tokens; Ollama ignores
`n`.

## Batch APIs
Anthropic's Message Batches API and OpenAI's Batch API process large offline jobs asynchronously at about half the
price, with results within 24 hours (often much sooner). Triage of a backlog is a natural fit; interactive triage is
not.

## Reference
Anthropic, "Building effective agents" (Dec 2024): the workflow/agent distinction and the patterns in TEXTBOOK §3.
