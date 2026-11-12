# Node 16 TEXTBOOK: agent frameworks

You've written an agent loop (Node 02), tool definitions and error handling (Nodes 03, 05), context management
(Node 06), evals (Node 04), routing (Nodes 09, 15), retries and durable runs (Node 14). Every agent framework is a
packaged opinion about some of those pieces. This node uses two well-known ones that sit at different layers, and
gives you a method for judging any other.

## §1 What a framework is made of
| Layer | You built it in | Pydantic AI | LangGraph |
|---|---|---|---|
| Model clients and a neutral message format | Node 02 adapters | yes, many providers | no (bring your own; LangChain integrations exist) |
| The tool-calling loop | Node 02 `run_agent` | yes (`Agent.run`) | you draw it as a graph |
| Tool schemas | Node 05 (hand-written JSON Schema) | from Python signatures, or `Tool.from_schema` | yours |
| Structured output + validation retries | Node 09 | yes (`output_type`, retries) | yours |
| Usage limits / budgets | Node 02 `Budget` | `UsageLimits` (requests, tokens, cost) | yours |
| Fallback models | Node 14, config `[fallbacks]` | `FallbackModel` | yours |
| Human approval | Node 03 (blocking), Node 14 (durable) | deferred tools (`requires_approval`) | `interrupt()` + checkpointer |
| Persistence / resume | Node 14 journal | serialise the message history yourself; durable-execution integrations | checkpointer after every step |
| Observability | Node 01 traces (OpenTelemetry) | OpenTelemetry (Logfire or any backend) | callbacks; LangSmith or OpenTelemetry |
| Evals | Node 04 | a separate evals package | LangSmith (separate) |

The table is the whole argument in small: neither framework replaces everything you built, and each replaces
different things.

## §2 What you buy, what you pay
**You buy** working code for the commodity parts (provider quirks, schema generation, streaming, retries), shared
vocabulary with other engineers, documentation, and features you'd build later anyway (approvals, durable
execution integrations, graph visualisation).

**You pay** in:
- *Churn*: Pydantic AI was at 2.65 in November 2026, with deprecations along the way (this node's converter has to
  handle a message part that was deprecated during 2.x). Pin versions, read changelogs, budget for upgrades.
- *Depth*: when something goes wrong, the stack trace runs through someone else's async code. You need to know
  the framework's model well enough to debug it; the AGENT-OFF tasks are that.
- *Hidden behaviour*: default retries, default instructions, how tool errors are fed back, how output validation
  re-prompts. These change tokens, cost and behaviour. Measure the framework the way you'd measure a prompt change.
- *Lock-in*: message formats, state formats and persisted histories in the framework's shape. A port's exit cost is
  mostly data, not code.

**The test that matters** is the one you already have: run your evals through the framework. If the graders can't
see the conversation, you can't compare. That's why this node starts with the converter.

## §3 Porting to Pydantic AI
The port keeps everything that defines the assistant's behaviour (prompt v2, the v2 Shopfront tools, the budget)
and hands the loop to `Agent.run`. Things that turn out to matter:

- **Tools from a schema.** Shopfront's tools already have JSON Schemas (Node 05); `Tool.from_schema` keeps them
  byte-identical, so tool descriptions don't drift between implementations.
- **Errors.** In the course loop a business error ("refund not allowed") is a tool result with `is_error`. Pydantic
  AI has three options: return a value, raise `ModelRetry` (the model is asked to try again; it counts against a
  retry limit, and exceeding it fails the run), or raise `ToolFailed` (a terminal failure the model sees as a
  failed result, without spending a retry). The port raises `ToolFailed`, which matches the course's semantics;
  the converter maps a failed result back to `is_error`. Choosing between them is a behaviour decision, and it's
  yours.
- **Hidden defaults** (found by reading what the port actually sends, YOU_DO task 5): Pydantic AI runs a
  response's *sync* tools concurrently in worker threads unless told otherwise (the port sets `sequential=True`:
  Shopfront's tools share one SQLite connection, and order matters for side effects); its default `max_tokens` is
  much larger than the course's 2048 (the port sets it); it may mark tool schemas `strict`; and it fills
  `usage.cost` with an estimate from its own price data (the port ignores it and prices from the course table, or
  uses the cost the provider reported).
- **Usage and budget.** Pydantic AI's `input_tokens` *include* cache reads and writes; the course's exclude them.
  And the budget must see every request as it happens, not the run's total afterwards: a wrapper model checks the
  budget before and charges after each request, so a run that fails half-way has still paid for what it used.
  Every port has a dozen of these.
- **History.** The framework's own message list is the conversation state; you persist it
  (`ModelMessagesTypeAdapter`, or the `ConversationStore` interface Pydantic AI added in 2.x, which ships with an
  in-memory store) and pass it back as `message_history`. A converter gives the graders the course format.
- **Approval.** Mark a tool `requires_approval`; the run ends with `DeferredToolRequests` instead of an answer;
  resume with `DeferredToolResults` and the saved history. Between the two runs, *you* store the history, so the
  durability is yours: the same job as Node 14's journal, without the per-tool-call intents.

## §4 Porting to LangGraph
LangGraph doesn't call models; it runs a state machine you draw. The port's graph is the Node 02 loop drawn out:
an `agent` node (your ChatModel, budget and tracing, unchanged) and a `tools` node, with a conditional edge between
them. What LangGraph adds is the **checkpointer**: after every step it saves the state (here, the message list), so
a thread can be resumed in another process, inspected step by step, or rewound.

**`interrupt()`** pauses inside a node and saves the state; `Command(resume=...)` continues. The catch: on resume
LangGraph **re-runs the interrupted node from the top**. Whatever the node did before `interrupt()` happens again.
So in `tools_node` all approvals are requested in one interrupt *before* any tool runs (YOU_DO task 3). The same
applies to crashes: if the process dies inside a node, the resumed run repeats the whole node, including side
effects that already happened. Compare Node 14, which journals an intent per tool call and reconciles: LangGraph's
unit of durability is the node; yours was the tool call. LangGraph's docs say it directly: make nodes idempotent,
and put side effects in their own tasks/nodes.

## §5 Persistence compared
| | Node 14 journal | Pydantic AI | LangGraph |
|---|---|---|---|
| What's saved | each step: model response, intent, result, approvals | the history, when you save it (`ConversationStore`; durable-execution integrations: Temporal, DBOS, Prefect) | the full state after every node |
| Unit of recovery | one tool call | one run (or one activity, with an integration) | one node |
| Side effect interrupted mid-way | reconciled or `needs_human` | depends on what you saved | the node runs again |
| Approval waits across processes | yes (journal) | yes, if you persist history + deferred requests | yes (checkpointer) |
| Inspect / rewind | timeline | your logs | state history, time travel |

None of these is "correct"; they draw the line in different places. The question for your ADR is where Shopfront's
dangerous side effects sit relative to that line.

## §6 Measuring a port
Run the same tasks, same model, same prompt and tools through each implementation and the same graders. Expect
small differences and explain them from transcripts, not vibes: a different number of calls (how the framework
feeds errors back), more input tokens (extra instructions or schema transformations), different stops (limits
counted differently). Then look at the things a pass rate can't show: lines of code you maintain (the comparison
counts them), how a failure looks in a trace, what an upgrade would touch.

## §7 Choosing
Some defensible positions, depending on the team:
- **Keep the homemade loop** when it's small, well tested, and the team knows it; adopt libraries for the
  commodity layers instead (an SDK, a durable-execution engine, OpenTelemetry).
- **Adopt an agent framework** (Pydantic AI and peers) when you'd otherwise rebuild its features, many engineers
  touch the agent code, or you want its provider coverage. Keep your evals and your message format at the seams.
- **Adopt an orchestration framework** (LangGraph and peers) when the workflow itself is complex: many steps,
  branches, long pauses, human checkpoints, and you want them visible and resumable.
Whatever you choose, write down the exit plan: which data you'd have to convert, and which tests prove the new
implementation behaves the same.

## Key terms
abstraction layer · port · converter (seam) · `Tool.from_schema` · `ModelRetry` · deferred tools · message history ·
state graph · node · conditional edge · checkpointer · thread · `interrupt` / `Command(resume)` · node re-execution ·
idempotent node · lock-in · exit plan
