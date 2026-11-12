# Ticket SEC-08: The ops agent reads attacker-written text. Make that safe.

| | |
|---|---|
| **Estimate** | 2.5 days |
| **Cost cap** | ≈ $2 (detector work is free; adaptive attacks ≈ $0.20; defence comparison ≈ $1–1.50) · Free models: $0 but ≈ 300–500 requests (detector work is free) |
| **Prerequisites** | Node 02 (loop), Node 03 (permission gates, threat models), Node 04 (evals) |
| **You will touch** | `agentlab/security/detect.py`, `policy.py` (yours); ops agent, defences, plan executor, evals (agent); `evals/injections_mine.yaml`, `docs/threat-models/ops-agent.md` |
| **Done when** | `make grade N=08` green · detector TPR/FPR on dev and held-out logged · an adaptive attacker beat your detector, and you checked whether its text still fools the agent · defence table (ASR + utility) with failures read · threat model |

## Story
Staff want an operations assistant that reads reviews, tickets and orders, and can email customers and issue
refunds. That's private data, untrusted content and a way to act in the world: the lethal trifecta. The seeded
data already contains attacks (instructions to an "AI agent" in reviews, a shipping address that asks for the
customer list, tickets that try to override the system prompt). You'll write a detector and watch it get beaten, then
build defences that don't depend on the model saying no: allowlists from the trusted request, an information-flow
policy, human approval, and a plan-then-execute design where the model that reads attacker text can't act.

## Deliverables
1. `agentlab/security/detect.py::detect_injection`: **by hand** (AGENT-OFF).
2. `agentlab/security/policy.py::flow_policy`: **by hand** (AGENT-OFF).
3. Ops agent, five defences, plan executor, graders, evals, CLI: coding agent, from `SPEC.md`.
4. `evals/injections_mine.yaml`: five hand-written evasions of your own detector.
5. `docs/threat-models/ops-agent.md`.

## Time boxes
| Step | Box | Escape hatch |
|---|---|---|
| TEXTBOOK + attacks + predictions | 2.5h | |
| Detector | 2h | `git show solution/node-08:agentlab/security/detect.py`; then write your own |
| Breaking it | 1h | adaptive attacker only |
| Agent builds SPEC + review | 1.5h | `make solution N=08` |
| `flow_policy` | 1h | same, `policy.py` |
| Defence comparison | 1.5h | 3 defences: none, taint, plan |
| Threat model | 1h | |

## Rubric (0–2 each)
| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Detector | tests fail | tests pass | + held-out measured once, threshold chosen from costs |
| Breaking it | not done | adaptive attacker run | + hand-written evasions, and checked against the agent |
| Measurement | ASR only | ASR and utility | + benign utility, approvals, failures read per defence |
| Policy | tests pass | + table of cells | + you can say which attack each rule stops |
| Threat model | list of attacks | controls per attack | + residual risks, per-task tool sets, monitoring |
