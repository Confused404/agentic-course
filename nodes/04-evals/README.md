# Ticket EVAL-04: Turn the smoke detector into a measurement instrument

| | |
|---|---|
| **Estimate** | 3 days |
| **Cost cap** | ≈ $5 (dev suite × 3 models × 3 trials ≈ 200 trials, plus judge and simulator calls, plus a re-run) · Free models: $0 but ≈ 1,000+ requests (trials × turns, plus judge and simulator): needs the 1,000/day tier and still takes a couple of days; cut `--trials` to 1 for the first pass |
| **Prerequisites** | Nodes 02–03 |
| **You will touch** | `agentlab/evals/stats.py` (yours), the rest of `agentlab/evals/` (agent), `evals/support/mine.yaml` (yours), `docs/adr/0002-*` |
| **Done when** | `make grade N=04` green (incl. Tier 1 suite check) · live matrix report · judge calibrated on ≥ 20 labels · ADR 0002 · 3 tasks added from real failures |

## Story
"Is the assistant ready?" asks the founder. You have 10 cases and a 7/10. That's not an answer: it could be a
50% assistant having a good day. You'll build the instrument that can answer: 30 tasks (20% held out), state-based
graders and an LLM judge you've *checked*, simulated customers, statistics that admit uncertainty, a matrix across
three vendors, and a loop that turns tomorrow's production failures into next week's tests.

## Deliverables
1. `agentlab/evals/stats.py` (Wilson, pass@k, pass^k, task bootstrap, paired diff): **by hand** (AGENT-OFF).
2. The harness (tasks, graders, judge, simulated user, runner, report, flywheel, CLI): coding agent, from `SPEC.md`.
3. A live eval report across `fast`, `gpt-fast`, `local` on the dev split, with three failures read and classified.
4. Judge calibration: ≥ 20 of your own labels, agreement measured, disagreements explained.
5. `docs/adr/0002-default-model.md`: which model the assistant should use, defended with the report's numbers.
6. `nodes/04-evals/evals/support/mine.yaml`: 3+ tasks from real failures, each with golden and bad scripts.

## Time boxes
| Step | Box | Escape hatch |
|---|---|---|
| TEXTBOOK + self-check | 2.5h | |
| `stats.py` by hand | 1.5h | study `git show solution/node-04:agentlab/evals/stats.py`, rewrite |
| Agent builds harness + review | 3h | `make solution N=04` |
| Live matrix + reading failures | 3h | 2 models, 2 trials |
| Judge calibration | 1.5h | 12 labels |
| New tasks + ADR + flywheel | 2.5h | |

## Rubric (0–2 each)
| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Statistics | tests red | green | green, and you explain why trials aren't independent samples |
| Reading results | quotes pass rates | quotes intervals | refuses to rank models whose intervals overlap without a paired test |
| Judge | trusted blindly | calibrated | calibrated, plus one rubric weakness found and described |
| Dataset | none added | added tasks | added tasks have golden + bad scripts and come from real traces |
| Decision | none | model chosen | chosen via pass^k, cost per pass and Pareto, with a stated condition for revisiting |
