# Glossary

Terms used across the course, with the node that introduces them. Node TEXTBOOKs have the full treatment; each one
ends with its own list of key terms.

| Term | Meaning | Node |
|---|---|---|
| A2A (Agent2Agent) | An open protocol for one agent to discover another (agent card) and delegate tasks to it | E4 |
| Ablation | Removing one component at a time to measure what each contributes | 12 |
| Adapter | Code that maps one provider's API to the course's neutral message format | 02 |
| AGENT-OFF | Work you do by hand, never delegated to a coding agent; graded by tests | 00 |
| Agent loop | Call the model, run the tools it asks for, feed results back, repeat until it answers or a limit hits | 02 |
| Alias | A model name used in code (`fast`, `mid`) that config maps to a real provider and model | 00 |
| Approval (durable) | A pause for a human decision that is journaled, so the process can exit and resume later | 14 |
| Attack success rate (ASR) | Share of attack tasks where the attacker's goal was achieved | 08 |
| Backoff, full jitter | Wait a random time between 0 and an exponentially growing cap before retrying | 14 |
| Blended cost | (model cost + human cost × unresolved conversations) / conversations | 15 |
| Budget | A hard spending cap every live model call is charged against | 00, 02 |
| Cache (prompt) | Providers reuse the processed prefix of a request; reads are cheap, a changed prefix misses | 01, 15 |
| Cascade | Answer with a cheap model, escalate to a strong one when a signal fires | 09, 15 |
| Checkpointer | LangGraph's per-step state store that makes a thread resumable | 16 |
| Circuit breaker | Stop calling a failing provider for a cooldown; fail fast or use a fallback | 14 |
| Compaction | Replacing old conversation turns with a model-written summary | 06 |
| Confused deputy | A component with authority acting for a caller who lacks it (e.g. a customer id taken from a request body) | 13 |
| Context window / engineering | What the model sees on a call, and deciding what goes in it | 01, 06 |
| Converter (seam) | Code that maps a framework's messages back to your format so your evals still apply | 16 |
| Cost per resolution | Total model cost divided by conversations actually resolved | 15 |
| Deferred tools | Pydantic AI's mechanism for tool calls that wait for approval or external execution | 16 |
| Durable execution | Journaling each step so a run survives crashes and long pauses | 14 |
| Escalation (permissions) | Handing control to a human after repeated gate denials | 13 |
| Eval, grader, trial | A task with checks (graders), run one or more times (trials) | 04 |
| Fallback model | Another model (ideally another provider) used when the primary keeps failing | 14 |
| Flywheel | Mining production failures into new eval tasks | 04, 17 |
| Free mode | The course's default with only an OpenRouter key: every alias is a free model | 00 |
| Gate (launch) | A go/no-go decision computed from a scorecard and a written policy | 17 |
| Gate (permission) | Rules (and a classifier) deciding whether an agent action may run | 03, 13 |
| Handover | Passing a conversation to a person instead of failing in front of the customer | 15, 17 |
| Harness | Everything around a coding agent that makes long tasks work: progress files, checkpoints, verification | 12 |
| Held-out split | Tasks nobody tuned against; the honest estimate of quality | 04 |
| Hidden acceptance tests | Tests the agent can't see, run by the harness to catch overclaims | 12 |
| Idempotency key | A request id that makes a retried side effect happen at most once | 14 |
| Intent (journal) | A record written before a side effect runs, so recovery knows it may have happened | 14 |
| Interrupt | LangGraph's pause for human input; the node re-runs from its start on resume | 16 |
| Kill switch | A config flag that turns the assistant off without a deploy or a model call | 17 |
| Least privilege | Exposing only the tools and data a principal needs, at listing and at call time | 11, 13 |
| LoRA | Training small adapter weights instead of the whole model | E2 |
| MCP | Model Context Protocol: a standard way to expose tools and resources to agents | 11 |
| Memory (long-term) | Facts written by the agent and read in later sessions, with a write policy | 06 |
| Orchestrator-workers | One agent splits a task, workers do parts in isolated contexts, results are reconciled | 10 |
| Overclaim | An agent reporting success that hidden tests don't confirm | 12 |
| p50 / p95 | Median and 95th-percentile latency; the tail is what customers complain about | 15 |
| pass@k / pass^k | At least one of k trials passes / all k trials pass | 04 |
| Pinning (tools) | Fingerprinting MCP tool definitions to detect changes (rug pulls) | 11 |
| Prefill / decode | Reading the prompt / generating output tokens; they have different speeds | 01, 15 |
| Prompt injection | Untrusted content that tries to make the model follow its instructions | 08 |
| Reconcile | After a crash, check whether a side effect happened before deciding to run it | 14 |
| Retrieval (RAG, agentic search) | Fetching relevant documents into context, in one shot or by tool calls | 07 |
| Rollout (percentage) | Enabling a feature for a stable, hashed share of customers | 17 |
| Runbook | Per-alert instructions: meaning, checks, safe actions, owner | 17 |
| Sandbox | Isolation that limits what a command can touch, regardless of the gate | 03, E3 |
| Scope | A permission carried by a token (e.g. `refunds:write`) | 13 |
| Scorecard | Launch metrics from earlier runs, each with a source and a date | 17 |
| Shadow price | Pricing free-model token counts as a paid model, to make cost experiments meaningful | 15 |
| Skill | Instructions and resources loaded only when relevant (progressive disclosure) | 12 |
| Spotlighting | Marking untrusted content so the model treats it as data | 08 |
| Stop reason | Why a model call ended: end_turn, tool_use, max_tokens, refusal... | 02 |
| Streaming events | Text and tool-argument fragments delivered as the model generates them | 17 |
| Structured output | Constraining the answer to a JSON schema, with validation | 09 |
| Thinking / reasoning tokens | Tokens a model spends before answering; billed as output, count toward max_tokens | 01 |
| Token (auth) | A signed, short-lived credential naming the subject, audience, scopes and expiry | 13 |
| Tool poisoning / shadowing / rug pull | MCP attacks via tool descriptions, name collisions, or definitions that change later | 11 |
| Unit economics | Cost per conversation, per resolution, and blended with human handling | 15 |
| Utilization (GPU) | The share of time a self-hosted GPU does useful work; decides its cost per token | 15, E5 |
| Wilson interval | A confidence interval for a pass rate that behaves well with few trials | 04 |
