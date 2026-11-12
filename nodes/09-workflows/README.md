# Ticket FLOW-09: Triage 240 tickets: rules, workflows, or an agent?

| | |
|---|---|
| **Estimate** | 1.5 days |
| **Cost cap** | ≈ $1 (rules are free; the full method comparison ≈ $0.60; drafting ≈ $0.20) · Free models: $0 but ≈ 400–600 requests (rules are free) |
| **Prerequisites** | Node 04 (evals), Node 05 (structured outputs, one-change experiments), Node 08 (untrusted input) |
| **You will touch** | `agentlab/workflows/rules.py`, `selective.py` (yours); triage methods, drafting loop, evals, CLI (agent); `TRIAGE_SYSTEM` (yours after review); `docs/adr/0006-*` |
| **Done when** | `make grade N=09` green · rules measured on dev and held-out · six-method comparison read (stages, confusions, confidence) · one prompt experiment logged · drafting rounds judged · ADR 0006 |

## Story
Support has 240 open tickets and an empty category column. Someone has proposed "an AI agent that triages
everything". Before building that, you'll find out how much plain rules can do, what one structured model call adds,
what parallel voting and a cheap-to-strong cascade buy, and what a full agent costs for the same job. Then you'll ship
the cheapest design that meets an accuracy bar, with a human queue for the rest.

## Deliverables
1. `agentlab/workflows/rules.py::classify_by_rules`: **by hand** (AGENT-OFF).
2. `agentlab/workflows/selective.py`: coverage curve and threshold choice, **by hand** (AGENT-OFF).
3. Triage methods (single call, voting, cascade, agent), drafting loop, evals, CLI: coding agent, from `SPEC.md`.
4. One logged prompt experiment on the triage prompt.
5. `docs/adr/0006-ticket-triage.md`.

## Time boxes
| Step | Box | Escape hatch |
|---|---|---|
| TEXTBOOK + predictions | 1.5h | |
| Rules | 1.5h | `git show solution/node-09:agentlab/workflows/rules.py` |
| Agent builds SPEC + review | 1.5h | `make solution N=09` |
| Selective prediction | 45m | |
| Comparison + experiment | 2h | skip the agent method |
| Drafting | 1h | three tickets |
| ADR | 30m | |

## Rubric (0–2 each)
| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Baseline | none | rules pass tests | + held-out measured, overfitting discussed |
| Comparison | accuracy only | + cost, latency | + stages, confusions, easy/hard slices, paired CI |
| Confidence | not used | threshold picked | + checked on held-out, coverage cost stated |
| Workflow judgment | "use the agent" | a design | the cheapest design meeting the bar, with the human queue sized |
