# Electives

Each elective is a self-contained extension you can do after the node it builds on. They're shorter than nodes
(half a day to two days), lighter on scaffolding (no coding-agent SPEC: you build what's needed), and more
time-sensitive: every one has a dated "check before relying on this" list. Do them in any order.

| Elective | After | Question it answers | Est. | Cost |
|---|---|---|---|---|
| [E1 Computer & browser use](E1-computer-use/README.md) | Node 08, 11 | When is driving a UI worth it, and how do you keep it safe? | 1d | ≈ $1–3 (vision tokens) |
| [E2 Fine-tuning vs harness](E2-finetuning/README.md) | Node 09 | Does a fine-tuned small model beat a prompted big one on triage? | 1.5d | $0 on Kaggle's free GPU |
| [E3 Sandbox internals](E3-sandbox-internals/README.md) | Node 03, 13 | What actually stops an agent's shell command, and what doesn't? | 1d | $0 |
| [E4 Agent-to-agent (A2A)](E4-a2a/README.md) | Node 11, 13 | When do agents talk to agents instead of to tools? | 1d | ≈ $0.20 |
| [E5 Self-host an open model](E5-self-hosting/README.md) | Node 15 | What does "running your own model" cost, on free compute? | 1–2d | $0 (Modal: free credits, card on file) |

Rules that still apply: budgets on every live call, secrets only in `.env` or the platform's secret store, and
nothing you expose to the internet without authentication.
