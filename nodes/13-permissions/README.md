# Ticket SEC-13: "Let the agents run unattended, without handing them the keys"

| | |
|---|---|
| **Estimate** | 1.5 days |
| **Cost cap** | ≈ $0.05–0.10 (a vote is ≈ 700 input tokens; the YOU_DO 5 comparison is ≈ 400 votes); rules-only runs and all token work are free. Free OpenRouter models: ≈ 400 requests for YOU_DO 5, beyond the lowest daily allowance: run one method a day, or point `fast` at a cheap paid model |
| **Prerequisites** | Node 03 (permission gate), Node 08 (prompt injection), Node 09 (voting, classifier evals), Node 11 (MCP) |
| **You will touch** | `agentlab/authz/tokens.py::verify_token` (yours); scoped sessions, gate v2, evals, CLI (agent); `nodes/13-permissions/evals/redteam.yaml` (yours); `docs/adr/0010-*` |
| **Done when** | `make grade N=13` green · gate comparison read, misses explained · ≥ 10 red-team actions written, measured, and the gate hardened · ADR 0010 |

## Story
Two asks from the platform team. First: shopdev and the support agent should run overnight without someone
clicking "approve" on every command, and without becoming the incident report. Second: Shopfront's MCP server is
going to be reachable over HTTP, so it needs to know who's calling and what they may do. You'll build the gate and
the token checks, measure the gate on a labelled set, attack it, and write down what you'd trust it with.

## Deliverables
1. `verify_token`: **by hand** (AGENT-OFF). Security parsing is exactly the code you should be able to write and
   review yourself.
2. Scoped sessions, the two-stage gate, the gate evaluation and CLI: coding agent, from `SPEC.md`.
3. The gate comparison on the labelled set.
4. `evals/redteam.yaml`: at least 10 actions of your own that try to get past the gate, with results before and
   after your fixes.
5. `docs/adr/0010-unattended-permissions.md`.

## Time boxes
| Step | Box | Escape hatch |
|---|---|---|
| TEXTBOOK + predictions | 1h | |
| verify_token | 1.5h | `git show solution/node-13:agentlab/authz/tokens.py` |
| Agent builds SPEC + review | 2h | `make solution N=13` |
| Gate comparison | 1h | `--skip-denied` |
| Red team + hardening | 2h | 5 actions |
| ADR | 30m | |

## Rubric (0–2 each)
| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Tokens | tests fail | tests pass | + you can name the attack behind every check |
| Gate measurement | accuracy only | FP and miss rates | + per category, cost, share decided by rules, threshold trade-off |
| Red team | none | actions written | misses found, fixed, and the FP cost of the fix measured |
| Decision | "the classifier handles it" | a configuration | a configuration plus what bounds a miss (sandbox, secrets, egress, scopes, escalation) |
