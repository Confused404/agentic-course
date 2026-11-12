# Ticket LAUNCH-17: "Ship the support assistant to 10% of customers"

| | |
|---|---|
| **Estimate** | 3.5 days |
| **Cost cap** | ≈ $3–6 for fresh launch evidence on paid models (a Node 04 run with held-out tasks and 3 trials ≈ $2–4, a Node 15 bench of your launch configuration ≈ $1, a Node 08 security run ≈ $1), plus a few cents of manual testing. The drill, the gate and all tests are free. Free models: $0 but ≈ 1,500 requests: plan it over several days on the 1,000/day tier |
| **Prerequisites** | All of Parts I–VI. Every earlier node's evidence feeds this one |
| **You will touch** | `agentlab/launch/{stream.py,gate.py}` (yours); streaming in the Node 02 adapters and Node 14's `ResilientModel`, the launch service, scorecard, monitor, server and CLI (agent); `config/launch.toml`, `nodes/17-capstone/launch_policy.toml`, `docs/RUNBOOK.md`, `docs/adr/0014-*` (yours) |
| **Done when** | `make grade N=17` green · a scorecard built from **your** runs passes **your** gate (or you've written why not) · the drill's alerts fire in every incident and never in normal traffic · a runbook a colleague could follow · a separate agent reviewed the launch · ADR 0014 |

## Story
Launch day is Monday. The founder's conditions: no customer sees a stack trace, nobody can read another
customer's orders, it can be switched off in one minute, and someone knows within ten minutes if it goes wrong.
Product wants answers to appear as they're written, not after a ten-second blank. Finance wants the cost per
resolution you promised in Node 15. You have everything you need; you've built it over sixteen nodes. Now it has
to work together, be measured together, and be operated.

## Deliverables
1. `stream.py::assemble` and `gate.py::launch_decision`: **by hand** (AGENT-OFF). The first decides what a
   half-finished stream means; the second decides whether you launch.
2. Streaming end to end, the launch service, scorecard, monitor, HTTP API and CLI: coding agent, from `SPEC.md`.
3. Your launch configuration and gate policy, defended in ADR 0014.
4. A scorecard from fresh runs of your launch configuration, and the gate's verdict.
5. A tuned set of alerts (the drill) and `docs/RUNBOOK.md`.
6. A launch review by a separate agent (Node 12's evaluator idea), and your response to it.

## Time boxes
| Step | Box | Escape hatch |
|---|---|---|
| TEXTBOOK + predictions | 1.5h | |
| stream.py + gate.py | 2h | `git show solution/node-17:agentlab/launch/stream.py` |
| Agent builds SPEC + review | 3h | `make solution N=17` |
| Launch configuration + fresh evidence | 1 day (mostly waiting) | reuse earlier runs and mark them stale |
| Gate policy + scorecard | 2h | |
| Drill + alerts + runbook | 3h | |
| Launch review + ADR + retrospective | 3h | |

## Rubric (0–2 each)
| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Evidence | "the demo worked" | a scorecard | + fresh, from the launch configuration, with intervals; you can say what each metric can't show |
| Safety | auth bolted on | token, scopes, kill switch | + rollout, handover on every failure path, privacy-safe logs, the attack suite in the gate |
| Operability | none | alerts exist | + drill-tuned alerts, a runbook that names owners, a rollback that takes one minute |
| Judgement | ships anyway | gate decides | + you can argue for the thresholds, list what you'd watch in week one, and when you'd widen the rollout |
