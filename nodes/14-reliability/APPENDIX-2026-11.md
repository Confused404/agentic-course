# Appendix (dated 2026-11): reliability in practice

## Provider errors and retries
- **Anthropic API**: 429 `rate_limit_error` (your limits; usually with a `retry-after` header in seconds) and 529
  `overloaded_error` (the API is overloaded for everyone). The official SDKs retry connection errors, 408, 409,
  429 and 5xx twice by default with exponential backoff and honour `retry-after`; change it with `max_retries` on
  the client (or per request with `with_options`). A 429 can also mean a **spend cap** was reached: no wait fixes
  that, so alert instead of retrying.
  https://docs.claude.com/en/api/errors · https://learn.microsoft.com/en-us/microsoft-cloud/dev/dev-proxy/concepts/anthropic-529-overloaded-error
- **OpenAI Python SDK**: also retries twice by default (connection errors, 408, 409, 429, ≥ 500), configurable with
  `max_retries`. Both SDKs expose the HTTP response on their errors (`err.response.headers`), which is where
  `retry_after_s` reads `retry-after`. https://github.com/openai/openai-python#retries
- **OpenRouter**: the `models` array (OpenAI-compatible endpoint, `extra_body={"models": [...]}`) tries the listed
  models in order when one errors, and by default *any* error can trigger it, including context-length errors and
  rate limits; you're billed for the model that answered, named in the response's `model` field (log it: that's
  your fallback rate). On the Anthropic-compatible endpoint the equivalent is `fallbacks` (at most 3, not combinable
  with `models`). Free (`:free`) models have per-minute and per-day request limits: once the **daily** limit is
  hit, every retry is another 429 until tomorrow, so a retry policy for free models needs a cap on total waiting,
  not just on attempts. https://openrouter.ai/docs/guides/routing/model-fallbacks · https://openrouter.ai/docs/api-reference/limits
- **Backoff with jitter**: Marc Brooker's AWS Architecture Blog post "Exponential Backoff And Jitter" (2015) is
  still the reference for why full jitter works; the AWS Builders' Library article "Timeouts, retries, and backoff
  with jitter" adds retry budgets and why retries at several layers multiply.
  https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/ ·
  https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/
- **Idempotency keys**: Stripe's API is the standard example: send an `Idempotency-Key` header and a retried POST
  returns the first result instead of acting twice. Ask whether each side-effecting API your tools call supports
  something similar before writing a reconciler. https://docs.stripe.com/api/idempotent_requests

## Durable execution for agents
- **Temporal**: workflows are replayed from an event history; model and tool calls run as activities. The OpenAI
  Agents SDK integration for Temporal's Python SDK has been generally available since March 23, 2026, and Temporal
  lists integrations for Pydantic AI and the Vercel AI SDK as well. Workflow code must be deterministic.
  https://temporal.io/blog/announcing-openai-agents-sdk-integration · https://pypi.org/project/temporalio-openai-agents/
- **DBOS**: durable workflows as a library, with checkpoints in Postgres (no separate server); 2026 releases target
  agent frameworks (e.g. middleware for the Vercel AI SDK). https://docs.dbos.dev/
- **LangGraph**: a checkpointer plus a `thread_id` gives durable execution; `interrupt()` pauses for a human and
  `Command(resume=...)` continues, even days later. Durability modes `exit`, `async` and `sync` trade speed for how
  much a crash can lose (`sync` writes each checkpoint before the next step). Its docs ask you to wrap side
  effects in tasks/nodes so they aren't re-run on resume, the same reasoning as this node's intent/result pair.
  https://docs.langchain.com/oss/python/langgraph/durable-execution · https://docs.langchain.com/oss/python/langgraph/interrupts
- Node 16 ports this node's support agent to a framework; compare what its persistence gives you with this journal.

## Observability
- **OpenTelemetry GenAI semantic conventions** (`gen_ai.*`): every attribute, span, metric and event is still at
  *Development* stability as of this writing. In semantic-conventions v1.42.0 (June 12, 2026) they moved out of the
  main repository into `open-telemetry/semantic-conventions-genai`, and attribute names have changed within 2026.
  Pin the version you emit and expect renames. https://github.com/open-telemetry/semantic-conventions-genai
- Claude Code, OpenAI Codex and VS Code Copilot emit OpenTelemetry telemetry for their agent sessions (check each
  tool's docs for which signals are stable); useful when your coding agents are part of the system you operate.

## Check before relying on this appendix
SDK retry defaults and the status codes they retry; OpenRouter's limits for free models (they've changed several
times); whether your durable-execution integration checkpoints per tool call or per agent turn; the GenAI
conventions' stability.
