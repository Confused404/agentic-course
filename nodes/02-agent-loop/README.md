# Ticket AGENT-02: Ship a support assistant on a loop you wrote yourself

| | |
|---|---|
| **Estimate** | 1.5 days |
| **Cost cap** | ≈ $1 (live evals on three models, plus manual testing) · Free models: $0 but ≈ 150 requests |
| **Prerequisites** | Node 01 (you know the wire formats and why they differ) |
| **You will touch** | `agentlab/agent/loop.py` (yours), `agentlab/{tools,llm,assistant,evals}/` (agent), `shopfront/app.py`, `docs/adr/` |
| **Done when** | `make grade N=02` green · live evals run on ≥ 2 vendors · ADR 0001 written · trace-based failure analysis logged |

## Story
The founder wants the support chat panel working this week: order lookups, refunds within policy,
cancellations, escalations. You've seen how differently vendors behave (Node 01), so you won't marry one:
the assistant must run unchanged on Claude, a GPT-family model and a local open model. And because the
assistant can move money, you want proof it does the right thing, measured from the database rather
than from what it says.

## Learning objectives
See TEXTBOOK. In short: loop invariants and stop conditions, provider-neutral adapters, tools as a model-facing
interface (errors as data, session-bound identity), bounding cost, and outcome-based evals.

## Deliverables
1. Two throwaway raw loops, one per vendor SDK (`nodes/02-agent-loop/scratch/`, ungraded, **by hand**).
2. `agentlab/agent/loop.py::run_agent`: **by hand** (AGENT-OFF), passing `tests/test_loop.py`.
3. Adapters, tool registry, support tools, assistant, mini eval runner, web endpoint: your coding agent, from `SPEC.md`.
4. `docs/adr/0001-canonical-message-model.md`: your critique of `agentlab/llm/types.py`.
5. Live eval results on ≥ 2 vendors, with a failure analysis in `LEARNING_LOG.md`.

## Time boxes
| Step | Box | Escape hatch |
|---|---|---|
| TEXTBOOK + self-check | 1.5h | |
| Raw loops (two SDKs) | 1.5h | skip the second one; read your first against TEXTBOOK §4 |
| `run_agent` by hand | 2h | `make solution N=02`, read `loop.py`, delete it, rewrite from memory |
| Agent builds SPEC + your review | 2h | `make solution N=02` |
| Live evals + trace analysis | 2h | run on one vendor only |
| ADR + browser test | 1h | |

## Rubric (0–2 each)
| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Loop correctness | tests red | tests green | green, and you can point to the line that enforces each invariant in TEXTBOOK §2 |
| Adapter review | not reviewed | read | found at least one place the SPEC's mapping loses information, and noted it in the ADR |
| Eval analysis | pass rate only | failures listed | each failure classified (selection / argument / interpretation / environment) from the trace |
| Vendor comparison | one vendor | two | three, with cost per passed case |
| Safety instinct | | tried to break it | found a way to make it misbehave, or argued convincingly why the design prevents it |
