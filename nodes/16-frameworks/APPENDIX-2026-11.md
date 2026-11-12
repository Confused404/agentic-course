# Appendix (dated 2026-11): frameworks in practice

## Versions used here
`pydantic-ai 2.65.0`, `langgraph 1.2.19`, `langgraph-checkpoint-sqlite 3.1.3` (pinned in the `frameworks` extra).
Both projects release often; re-run this node's tests after any upgrade.

## Pydantic AI
- Agents, tools (`Tool`, `Tool.from_schema`, `RunContext` dependencies), `UsageLimits` (requests, tokens, tool calls,
  cost), `FallbackModel`, structured output with validation retries, deferred tools for human approval
  (`requires_approval`, `DeferredToolRequests`, `DeferredToolResults`), message history serialisation
  (`ModelMessagesTypeAdapter`), test models (`FunctionModel`, `TestModel`), OpenTelemetry instrumentation (Logfire or
  any OTel backend; the library prints a banner about it unless `PYDANTIC_AI_NO_BANNER=1`, which the course sets).
- Durable execution integrations ship in the package: `pydantic_ai.durable_exec.temporal`, `.dbos`, `.prefect`.
- Token accounting: `RequestUsage.input_tokens` includes cache reads and writes; `cost` may be set when the provider
  or price data allows.
- Deprecations seen during 2.x: `RetryPromptPart` (a retry answering a tool call is now a `ToolReturnPart` with
  `outcome="retried"`; other retries are `RetryFeedbackPart`), slated for removal in v3. `result.usage` became a
  property.
  https://ai.pydantic.dev

## LangGraph
- `StateGraph` with reducer-annotated state, conditional edges, `interrupt()` and `Command(resume=...)` for human
  input, checkpointers (in-memory in core; SQLite and Postgres as separate packages), `thread_id` per conversation,
  state history and time travel. Durability modes `exit`, `async` and `sync` trade speed for how much a crash can
  lose. The docs ask for deterministic, idempotent nodes and side effects wrapped in tasks/nodes, because a resumed
  node runs again from its start.
  https://docs.langchain.com/oss/python/langgraph/durable-execution ·
  https://docs.langchain.com/oss/python/langgraph/interrupts
- `langgraph` depends on `langchain-core`; you don't need LangChain's model classes to use it (this port doesn't).

## The wider landscape (check current status before choosing)
Vendor SDKs with agent loops (OpenAI Agents SDK, Claude Agent SDK, Google's ADK), multi-agent frameworks (CrewAI,
Microsoft's agent framework), and durable-execution platforms with agent integrations (Temporal: the OpenAI Agents
SDK integration has been generally available since March 2026; DBOS; Restate). Apply the same method: map its
layers to what you built, run your evals through it, run a crash and an approval drill, count what you'd maintain.
