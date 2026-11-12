# Appendix (dated 2026-11): launching in practice

## Streaming wire formats
- **Anthropic Messages API** (`stream=True`): server-sent events `message_start` (with input usage),
  `content_block_start` (text, tool_use with id and name, thinking), `content_block_delta` (`text_delta`,
  `input_json_delta` with `partial_json`, `thinking_delta`, `signature_delta`), `content_block_stop`,
  `message_delta` (stop_reason, output usage), `message_stop`, plus `ping` and `error` events.
  https://platform.claude.com/docs/en/build-with-claude/streaming
- **OpenAI-compatible Chat Completions** (`stream=True`): chunks with `choices[0].delta` (`content`, `tool_calls` with
  an `index` and argument fragments), `finish_reason` on the last choice chunk, and usage in a final chunk only if
  you ask with `stream_options={"include_usage": true}`. OpenRouter follows this format and also sends comment
  lines to keep connections open (SDKs skip them).
  https://openrouter.ai/docs/api-reference/streaming
- Anthropic's fast mode (Node 15 APPENDIX) raises output tokens per second, which is what streaming makes visible;
  it doesn't shorten time to first token. Priority tiers are about capacity and availability under load; check what
  your provider's tier actually promises before counting on it for latency.

## Model lifecycle
Providers retire model versions on published schedules (Anthropic's deprecations page; OpenRouter marks models
as deprecated in its catalog). With aliases, switching is a config change; re-run the gate on the new model before
pointing the alias at it.
https://platform.claude.com/docs/en/about-claude/model-deprecations

## Observability for agents
OpenTelemetry GenAI conventions are still "Development" (Node 14 APPENDIX); pin what you emit. LLM observability
products (Langfuse, Arize Phoenix, Datadog LLM Observability, LangSmith, Logfire, among others) ingest OTLP; the
course's traces work with any of them (Node 00 Step 5).

## Check before relying on this appendix
The streaming event names (they gain new block types over time: citations, server tools); whether your provider
puts usage in the final chunk; your providers' deprecation dates for the models you launch on.
