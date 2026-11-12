# Ticket OPS-14: "The agent refunded her and never told her"

| | |
|---|---|
| **Estimate** | 1.5 days |
| **Cost cap** | ≈ $0.05–0.20 on paid `fast` (the default chaos run is 60 runs of 3–4 model calls). Injected faults never reach the provider, so they're free. Free models: ≈ 200 requests for the default chaos run, beyond the 50-a-day allowance: use `--seeds 1` (≈ 70 requests) on the 1,000/day tier, or split the configurations across two days (`--configs`). Tasks 2–5 are free |
| **Prerequisites** | Node 02 (the agent loop), Node 03 (side-effecting tools), Node 04 (evals), Node 09 (cost accounting), Node 12 (harness checkpoints) |
| **You will touch** | `agentlab/reliability/{retry.py,recovery.py}` (yours); resilient model, durable runner, chaos lab, CLI (agent); `docs/adr/0011-*` |
| **Done when** | `make grade N=14` green · chaos table read and every lost run explained · an approval survived a process exit · ADR 0011 |

## Story
Last Tuesday the model provider had a bad hour: 529s, then timeouts. Three things happened in support. Most
conversations just died with a stack trace in the logs. One customer got her refund issued, but the worker
crashed before the reply was sent, so she wrote back angry and a colleague issued a second one by hand. And the
big-ticket refund that was waiting for a manager's OK was lost when the deploy restarted the worker; nobody knew
it had been waiting.

Your job: make the agent survive a flaky provider, a crashing process, and a human who takes a day to answer, and
prove it with a chaos run instead of a promise.

## Deliverables
1. `retry.py` (`is_retryable`, `backoff_delay`) and `recovery.py` (`plan_recovery`): **by hand** (AGENT-OFF). The
   first decides when waiting helps; the second decides what is safe to do after a crash. Both are small, and both
   are exactly where a wrong guess costs money.
2. The resilient model wrapper, the durable runner, the chaos lab and the CLI: coding agent, from `SPEC.md`.
3. The chaos table for `naive`, `retry`, `requeue` and `durable`, with every lost or duplicated run explained.
4. A human approval that waits across processes: start, exit, approve from another shell, resume.
5. `docs/adr/0011-reliability.md`.

## Time boxes
| Step | Box | Escape hatch |
|---|---|---|
| TEXTBOOK + predictions | 1.5h | |
| retry.py + recovery.py | 2h | `git show solution/node-14:agentlab/reliability/recovery.py` |
| Agent builds SPEC + review | 2h | `make solution N=14` |
| Crash drills (free) | 45m | the parametrized durable test |
| Chaos run + analysis | 1.5h | `--seeds 1` |
| HITL across processes | 30m | |
| ADR | 30m | |

## Rubric (0–2 each)
| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Retry policy | retries everything | classified, backed off | + Retry-After, a cap, no double retry with the SDK, and you can say which errors are never retried and why |
| Recovery | re-runs the whole task | resumes from the journal | + side effects reconciled, never blindly repeated; you can name the crash points that need a reconciler |
| Measurement | "it works now" | chaos table | + every lost run and retried side effect explained, cost and latency of each layer, what the table can't show |
| Decision | "add retries" | a configuration | a configuration plus which tools need idempotency keys or reconcilers, and who answers approvals and how fast |
