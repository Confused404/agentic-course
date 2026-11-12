# Node 16 cheat sheet: frameworks

**Layers**: model clients · loop · tool schemas · structured output · limits · fallbacks · approvals · persistence
· observability · evals. Pydantic AI = an agent framework (clients + loop + tools + validation); LangGraph = an
orchestration framework (state graph + checkpointer + interrupts; bring your model).

**Measure a port like a prompt change**: same tasks, model, prompt, tools, graders; convert the framework's
messages to your format at the seam; explain differences from transcripts (calls, tokens, error feedback).

**Pydantic AI**: `Agent(model, instructions=, tools=[Tool.from_schema(...)])`, `run_sync(text, message_history=,
usage_limits=UsageLimits(...))`; tool errors: return text or raise `ModelRetry` (retry limit!); `input_tokens`
include cache; raise `ToolFailed` for a failed result the model sees (no retry spent); set `sequential=True` if
tools share state; charge the budget per request (a wrapper model); approval: `requires_approval` → `DeferredToolRequests` → resume with `DeferredToolResults` + saved
history (`ModelMessagesTypeAdapter`); tests: `FunctionModel`/`TestModel`.

**LangGraph**: `StateGraph(State)` with reducers (`Annotated[list, operator.add]`), nodes return deltas; compile with
a checkpointer (`SqliteSaver` for cross-process); `thread_id` per conversation; `interrupt(payload)` /
`Command(resume=...)`. **On resume the node re-runs from the top**: interrupt before side effects; idempotent nodes.

**Durability unit**: Node 14 = tool call (intent + reconcile) · LangGraph = node · Pydantic AI = whatever you persist
(or a Temporal/DBOS/Prefect integration).

**Adopt when** you'd rebuild its features, many people touch the code, or the workflow is a real graph; **pay** in
churn, debugging depth, hidden defaults, lock-in. Write the exit plan.

`python -m agentlab.frameworks compare --model fast`
`python -m agentlab.frameworks graph-start --model fast` → `graph-show THREAD` → `graph-resume THREAD --model fast --by you`
