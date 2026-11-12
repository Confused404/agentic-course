# Ticket HARNESS-12: "Make the coding agent finish a backlog without babysitting"

| | |
|---|---|
| **Estimate** | 2 days |
| **Cost cap** | ≈ $0.80 for the five-config ablation on `fast`; ≈ $2.50 with the cross-model runs. On free OpenRouter models: ≈ 550 requests per model for the ablation, so only with the higher daily allowance (or run two configs a day) |
| **Prerequisites** | Node 02 (loop), Node 03 (shopdev: tools, gate, sandbox), Node 04 (evals), Node 06 (context), Node 09 (evaluator-optimizer) |
| **You will touch** | `agentlab/harness/progress.py` (yours); hooks, session, evaluator, loops, evals, CLI (agent); your coding agents' hooks and skills (local settings only); `docs/adr/0009-*` |
| **Done when** | `make grade N=12` green · ablation run and read, with overclaims explained · the same backlog attempted in Claude Code or OpenCode with your own hook + skill, scored by `accept` · ADR 0009 |

## Story
Support engineering loved shopdev for bug fixes. Now they want it to work through a backlog: five promotions
features, one after another, overnight. The first attempt ("here's the backlog, go") came back with every feature
marked done and half of them broken. Your job: build the harness around the agent (state between sessions, checks
you control, a reviewer, guardrails) and measure which pieces actually earn their cost, on more than one model.

## Deliverables
1. `agentlab/harness/progress.py`: the harness's bookkeeping, **by hand** (AGENT-OFF).
2. Hooks, sessions, evaluator, harness loops, ablation evals, CLI: coding agent, from `SPEC.md`.
3. The ablation (5 configs on `fast`) and a cross-model run, read cell by cell.
4. A Claude Code or OpenCode run on the same backlog with your own stop hook and a skill, scored with `accept`.
5. `docs/adr/0009-harness.md`: the harness you'd run overnight, per model.

## Time boxes
| Step | Box | Escape hatch |
|---|---|---|
| TEXTBOOK + predictions | 1.5h | |
| progress.py | 1.5h | `git show solution/node-12:agentlab/harness/progress.py` |
| Agent builds SPEC + review | 3h | `make solution N=12` |
| Ablation + reading workspaces | 2.5h | `--configs single,loop+verify` only |
| Cross-model | 1h | two models |
| Coding-agent harness (hook + skill) | 2h | one agent |
| ADR | 30m | |

## Rubric (0–2 each)
| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Bookkeeping | tests fail | tests pass | + you can show a session the validation stopped from corrupting progress |
| Ablation | not run | table produced | every config's accepted/overclaims/cost explained from workspaces and events |
| Models | one model | two | the harness pieces each model needs, with the evidence |
| Coding agents | none | hook or skill | both, measured against the same acceptance tests |
| Decision | "use full" | a config | a config per model, the overclaim rate you accept, what you'd re-measure on a model upgrade |
