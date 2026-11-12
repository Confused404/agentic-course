# Ticket MULTI-10: "Should the analytics assistant use a team of agents?"

| | |
|---|---|
| **Estimate** | 2 days |
| **Cost cap** | ≈ $0.10–0.30 on `fast` for the main comparison; ≈ $0.30–0.50 for the `mid` runs. On OpenRouter free models: $0, but ≈ 75 requests per task for the three architectures (see below) |
| **Prerequisites** | Node 02 (loop, tracing), Node 04 (evals, paired comparisons), Node 05 (tool design), Node 09 (workflows vs agents) |
| **You will touch** | `agentlab/multi/reconcile.py` (yours); architectures, evals, CLI (agent); `LEAD_SYSTEM` (yours after review); `docs/adr/0007-*` |
| **Done when** | `make grade N=10` green · three architectures compared on 5 tasks · one brief experiment logged · one tool experiment logged · ADR 0007 |

## Story
Merchandising wants an assistant that answers catalogue questions like "which product in each category is rated
worst?" or "what should we restock?". A vendor demo showed "a team of AI analysts" doing this. Before anyone buys
it, you'll build the three serious options on the same tools, measure them against SQL-computed answers, and find
out what a team of agents actually buys: accuracy, speed, or just a bigger bill.

## Deliverables
1. `agentlab/multi/reconcile.py::reconcile`: **by hand** (AGENT-OFF). The merge step.
2. Single agent, orchestrator–workers, fixed map-reduce, evals and CLI: coding agent, from `SPEC.md`.
3. The comparison on all five tasks, with transcripts read.
4. One brief experiment (change `LEAD_SYSTEM`), one tool experiment (add a coarse tool).
5. `docs/adr/0007-multi-agent.md`.

## Time boxes
| Step | Box | Escape hatch |
|---|---|---|
| TEXTBOOK + predictions | 1.5h | |
| reconcile | 1h | `git show solution/node-10:agentlab/multi/reconcile.py` |
| Agent builds SPEC + review | 2h | `make solution N=10` |
| Comparison + transcripts | 2h | three tasks instead of five |
| Experiments | 1.5h | skip the tool experiment |
| ADR | 30m | |

## Requests on free models
Each task costs roughly 15 model calls for `single`, 30 for `orch` and 27 for `mapreduce`: about 75 for all three,
and ≈ 375 for the full five-task comparison. On OpenRouter's free variants that fits the higher daily allowance
(accounts with credits) but not the lowest one (≈ 50 requests a day): check `make check-env`. On the low allowance,
run one architecture on one task per sitting (`--archs single:fast --tasks top_units_90d`), or point `fast` at a cheap
paid model for this node (≈ $0.30 for everything). Free models also rate-limit per minute; the course paces free calls process-wide, so parallel
workers won't be faster in free mode (ignore the latency column there). In free mode `mid` is the same model as
`fast`, so an orchestrator "stronger than its workers" isn't possible: compare `fast` with `gpt-fast`/`local`. Rate-limit failures are reported as provider errors and excluded from
accuracy, for every architecture alike.

## Rubric (0–2 each)
| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Merge | tests fail | tests pass | + you can say which silent failure each rule prevents |
| Comparison | accuracy only | + tokens, wall time | + peak prompt, tokens by role, per-task failures explained from transcripts |
| Experiments | none | one logged | both, with predictions, and the tool experiment's lesson in the ADR |
| Judgment | "multi-agent is better" | a choice | the cheapest architecture that's right, the token multiple stated, the conditions that would change it |
