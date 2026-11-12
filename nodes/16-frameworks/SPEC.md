# SPEC: Node 16: the support assistant on Pydantic AI and LangGraph, compared with the same graders

**For the coding agent.** Read `AGENTS.md`. Background: TEXTBOOK §3–§6. Pinned: `pydantic-ai==2.65.0`,
`langgraph==1.2.19`, `langgraph-checkpoint-sqlite==3.1.3` (the `frameworks` extra in `pyproject.toml`).
**AGENT-OFF (the learner's; never write or edit them):** `agentlab/frameworks/convert.py::to_course_messages`
and `agentlab/frameworks/graph_nodes.py::tools_node`. Call them through their modules (`convert_module.…`,
`nodes_module.…`) so tests can substitute them.
**GIVEN (don't rewrite):** `convert.ERROR_PREFIX`, the stubs' signatures, `agentlab/frameworks/__init__.py`.
Reuse Node 02's ChatModel adapters and `Budget`, Node 04's `run_trial`/`Trial`/`load_tasks`/`load_trials`, Node
05's `get_prompt("v2")` and tool variant `"v2"`, Node 01's `tracing`, the course config (`resolve`, `api_key`,
`fallbacks_for`, `is_free_model`, `provider_config`, the `[free_tier]` rate).

## Files
```
edit    agentlab/evals/runner.py              (0)  a backwards-compatible hook
create  agentlab/frameworks/pydantic_port.py  (1)
create  agentlab/frameworks/graph_port.py     (2)
create  agentlab/frameworks/compare.py        (3)
create  agentlab/frameworks/__main__.py       (4)
```
`make grade-upto N=16` must stay green for 00–15.

## 0. `runner.py`
`run_trial(..., assistant_factory=None)`: when given, `assistant_factory(model, conn, task.customer_id, budget)`
replaces **both** places that construct `SupportAssistant` (first session and later sessions). The returned object
must offer the eval contract: `chat(text)` -> object with `.reply` and `.result.stop`/`.result.turns`;
`.transcript` (course Messages); `.turn_stats` (dicts with at least `action`, `input_tokens`, `output_tokens`);
optional `fixed_tokens`, `end_session`. (`assistant_opts` is not passed to a factory.) Also extend `error_kind`:
an exception group whose members are all provider errors, and `pydantic_ai` exceptions named `Model*Error`
(not `ModelRetry`), are "provider" (frameworks wrap provider failures in their own types).

## 1. `pydantic_port.py`
```python
class PacedModel(WrapperModel)     # request(): wait for a slot with agentlab.llm.pacing._wait_for_slot(rpm, ...)
                                   # (in a thread: asyncio.to_thread), rpm from [free_tier], then super().request
def pai_model(alias)               # resolve(alias): anthropic -> AnthropicModel(model, provider=AnthropicProvider(
    # api_key=api_key("anthropic"))); openrouter -> OpenRouterModel(id, provider=OpenRouterProvider(api_key=...)) for
    # [model, *fallbacks_for(model)], each wrapped in PacedModel if free, then FallbackModel(*models) when more than
    # one; ollama/openai -> OpenAIChatModel(model, provider=OpenAIProvider(base_url=..., api_key=... or "none"));
    # else ValueError
def pai_tools(registry) -> list[Tool]   # Tool.from_schema(fn, name, description, json_schema=spec.input_schema,
    # sequential=True) per tool (Pydantic AI would run sync tools concurrently in threads on our one SQLite
    # connection); fn(**kwargs) -> registry.execute(ToolUseBlock(<unique id>, name, kwargs)); an error result ->
    # raise pydantic_ai.exceptions.ToolFailed(text) (a failed result for the model, no retry spent)
MODEL_SETTINGS = {"max_tokens": 2048}
def build_agent(model, registry, system, *, approval_tools=frozenset()) -> Agent
    # Agent(model, instructions=system, tools=pai_tools(...), model_settings=MODEL_SETTINGS); with approval_tools:
    # those tools requires_approval=True and output_type=[str, DeferredToolRequests]
def course_usage(u, provider_details=None) -> Usage  # Pydantic AI input_tokens INCLUDE cache reads/writes: course
    # input_tokens = input - cache_read - cache_write (>= 0); output, cache_read, cache_write, reasoning
    # (output_reasoning_tokens); cost_usd = provider_details["cost"] if the provider reported one, else None
    # (u.cost is Pydantic AI's own estimate: ignore it)
class BudgetedModel(WrapperModel)  # (wrapped, budget, price_model, provider); request(): budget.check() if a budget;
    # super().request inside tracing.chat_span; course_usage(resp.usage, resp.provider_details); record_usage;
    # .responses += 1, .usage += u, .cost += budget.charge(price_model, u, provider=provider) if a budget
class PydanticSupportAssistant:    # (model, conn, customer_id, budget=None, *, max_requests=8, system_prompt=None
                                   #  -> get_prompt("v2"), tool_variant="v2", price_model=None, provider=None)
    # system formatted with {today}; tools make_support_tools(conn, customer, actor="agent:pydantic-ai",
    # variant=...); .model = BudgetedModel(model, budget, price_model or model.model_name, provider) and the agent
    # is built on it; .history (Pydantic AI messages), .transcript, .turn_stats, .fixed_tokens = {}
    def chat(text) -> PortReply(reply, PortResult(stop, turns, usage, cost_usd, final_text))
        # inside tracing.agent_span and capture_run_messages(): agent.run_sync(text, message_history=history,
        # usage_limits=UsageLimits(request_limit=max_requests)); UsageLimitExceeded -> stop "max_turns". In a
        # `finally` (so a failed run still keeps its part of the conversation): new = captured[len(old history):];
        # history = old + new; append convert_module.to_course_messages(new) to the transcript (prefixed with
        # Message.user(text) if it doesn't start with a user message); turn_stats entry: turn, calls (responses this
        # chat), input_tokens (total), cache_read_tokens, output_tokens, action "none". turns/usage/cost = the
        # BudgetedModel's deltas for this chat. Reply: the output text if stop is end_turn and non-empty, else
        # FALLBACK_REPLY.
def dump_history(history) -> str; def load_history(blob) -> list     # ModelMessagesTypeAdapter
```

## 2. `graph_port.py`
```python
class State(TypedDict, total=False): messages: Annotated[list, operator.add]  # course message dicts
                                     usage: Annotated[list, operator.add]     # one Usage dict per model call
                                     stop: str
def calls_this_turn(messages) -> int   # assistant messages after the last user message that has a text block
def build_graph(model, registry, system, *, budget=None, max_calls=8, approval_tools=frozenset(), checkpointer=None,
                model_opts=None)
    # agent node: calls_this_turn >= max_calls -> {"stop": "max_turns"}; else budget.check(); model.complete(
    # system, messages (from dicts), tools=registry.specs(), max_tokens=2048) in tracing.chat_span; budget.charge;
    # return the assistant message dict, its usage dict, stop = "tool_use" if it has tool calls with that stop
    # reason, else Node 02's mapping (end_turn/stop_sequence -> end_turn, max_tokens, refusal,
    # context_window_exceeded, else "other").
    # tools node: nodes_module.tools_node(state, registry=..., approval_tools=...).
    # START -> agent; agent -> tools if stop == "tool_use" else END; tools -> agent. Compile with the checkpointer
    # (default InMemorySaver()).
def sqlite_checkpointer(path)          # SqliteSaver(sqlite3.connect(path, check_same_thread=False)); .setup()
class GraphSupportAssistant:           # (model, conn, customer_id, budget=None, *, max_calls=8, system_prompt=None,
                                       #  tool_variant="v2", checkpointer=None, approval_tools=frozenset(),
                                       #  thread_id=None -> uuid)
    # actor "agent:langgraph"; one thread per conversation; .transcript, .turn_stats (as in §1), .fixed_tokens
    def chat(text) -> GraphReply(reply, GraphResult(stop, turns, usage, final_text, interrupts))
        # invoke({"messages": [user dict], "stop": ""}); the result covers what this call appended: new messages
        # -> transcript, turns = new assistant messages, usage = new usage dicts; stop "awaiting_approval" when the
        # thread has pending interrupts, else the state's stop ("tool_use" can't be final: report "other").
        # Reply rule as in §1.
    # chat() while approvals are pending -> GraphReply(<a "waiting for approval" message>,
    #   GraphResult("awaiting_approval", 0)) without touching the thread (a user message after unanswered tool calls
    #   is an invalid transcript). chat()/resume() update transcript and turn_stats in a `finally`.
    def pending_approvals() -> list[dict]   # the "approvals" of the thread's pending interrupts
    def resume(decisions) -> GraphReply     # invoke(Command(resume=decisions)); same accounting as chat()
```

## 3. `compare.py`
```python
IMPLS = ("native", "pydantic-ai", "langgraph")
SOURCES = {impl: [repo-relative files that implementation needs on top of the shared tools/prompts]}
def factory_for(impl, alias, *, pai_model_factory=None)    # native -> None; langgraph -> GraphSupportAssistant(model,
    # conn, cid, budget); pydantic-ai -> PydanticSupportAssistant((pai_model_factory or pai_model(alias))(), ...,
    # price_model=<alias's model id>, provider=<alias's provider>); else ValueError
def code_lines(paths) -> int           # non-blank lines not starting with "#"
def run_compare(tasks, impls, *, model_factory, alias, template_db, trials=1, budget=None, judge_factory=None,
                sim_factory=None, out_dir=None, pai_model_factory=None) -> list[Trial]
    # unknown impl -> ValueError before running; loop trial -> task -> impl; run_trial(model_label=impl,
    # assistant_opts={"system_prompt": get_prompt("v2"), "tool_variant": "v2"}, assistant_factory=factory_for(...));
    # out_dir -> trials.jsonl (truncated, one asdict line per trial)
def summarize(trials) -> {impl: {n, excluded (provider/timeout errors), pass_rate, errors, cost_per_conversation,
                                 calls_per_conversation, input_tokens_per_conversation (sum of turn_stats
                                 input_tokens), p50_latency_s, code_lines}}
def render(summary) -> str             # markdown table, then a line saying differences may be noise (Node 04)
```

## 4. `__main__.py`
```
python -m agentlab.frameworks compare --model ALIAS [--impls native,pydantic-ai,langgraph] [--suite PATH]
                                      [--trials 1] [--budget 1.0]
python -m agentlab.frameworks report RUN_DIR
python -m agentlab.frameworks graph-start --model ALIAS
python -m agentlab.frameworks graph-resume THREAD_ID --model ALIAS --by NAME [--deny] [--note TEXT]
python -m agentlab.frameworks graph-show THREAD_ID
```
- `compare`: default suite Node 04's `regression.yaml`; validate the alias, impls, trials >= 1, budget > 0
  **before** creating anything; out `new_run_dir(RUNS / "frameworks")` with a seeded template DB and `meta.json`;
  judge/simulator from `[evals]`; on an exception mid-run, report what was written.
- `graph-*`: like Node 14's HITL commands (models wrapped in Node 14's `ResilientModel`), on LangGraph: `RUNS/frameworks/graph/checkpoints.db` (sqlite
  checkpointer) shared by all threads; each `graph-start` gets a fresh shop copy in `graph/<THREAD>/shop.db` from
  a template; customer 9006, `approval_tools={"issue_refund"}`; thread id `refund-4826-<YYYYmmdd-HHMMSS>`; message
  "Order 4826 isn't what I wanted. Please refund it in full."; print the status, pending approvals and the
  resume command. `graph-resume` answers every pending approval with {approved, by, note} (nothing pending ->
  say so, exit 1). `graph-show` lists the thread's checkpoints (id, step, message count, last message's role and
  block types); no checkpoints file, or none for that thread -> say so, exit 1.

## Tests
`nodes/16-frameworks/tests/`: graders for the two AGENT-OFF functions (`test_convert.py`, `test_graph_nodes.py`,
the latter on a real graph), the ports with Pydantic AI's `FunctionModel` and a scripted course model, an
approval across two `GraphSupportAssistant` instances on one sqlite checkpointer, Pydantic AI's deferred approval,
and all three implementations through the same Node 04 graders.
