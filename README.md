# Agentic Engineering: a live-repo course

You will build, measure, break, harden and ship AI agents inside one realistic app: **Shopfront**,
a small online store with messy data, real policies, adversarial customers and a cost budget.
Every lesson is a **ticket** against this repo. You work on a branch, open a PR, and CI grades it.

The course is written for a professional software engineer working in Python, alongside a
coding agent (Claude Code, OpenCode, or both). It is **vendor-neutral**: you will run the
same agents on Anthropic, OpenAI-family and open-weights models, and decide between them
with evidence.

> Written 2026-11-04. Fast-moving details (model IDs, prices, protocol versions) are kept in
> config files and dated appendices. The textbooks teach what stays true when those change.

---

## Course map

| Part | Node | Ticket | Est. |
|---|---|---|---|
| **0** | [00 Setup](nodes/00-setup/README.md) | Run Shopfront, models from 3 vendors on one free key, read your first trace | 0.5d |
| **I: Foundations** | [01 LLMs for agent builders](nodes/01-llm-internals/README.md) | Six experiments on how models actually behave | 2d |
| | [02 The agent loop](nodes/02-agent-loop/README.md) | Hand-write the loop on two APIs, build adapters, first evals | 1.5d |
| | [03 A coding agent](nodes/03-coding-agent/README.md) | `shopdev`: edit tool, permission gate, sandbox, threat model | 3d |
| **II: Measurement** | [04 Evals](nodes/04-evals/README.md) | Noise, statistics, pass^k, state grading, CI tiers | 3d |
| | [05 Prompt & tool design](nodes/05-prompt-tool-design/README.md) | Improve the assistant with measured changes only | 1.5d |
| **III: Context & trust** | [06 Context engineering & memory](nodes/06-context-memory/README.md) | 50-turn chats, compaction, long-term memory | 2–2.5d |
| | [07 Retrieval](nodes/07-retrieval/README.md) | RAG vs agentic search, scored | 2.5d |
| | [08 Prompt injection](nodes/08-prompt-injection/README.md) | Break your own filter, fix the architecture | 2.5d |
| **IV: Composition** | [09 Workflow patterns](nodes/09-workflows/README.md) | Ticket routing; when *not* to use an agent | 1.5d |
| | [10 Multi-agent](nodes/10-multi-agent/README.md) | Single vs multi-agent, measured | 2d |
| | [11 MCP & interoperability](nodes/11-mcp/README.md) | Shopfront as an MCP server; tool poisoning | 1.5d |
| **V: Building with agents** | [12 Harness engineering](nodes/12-harness/README.md) | Generator/evaluator, ablations, Skills, Ralph loops | 2d |
| **VI: Production** | [13 Permissions & auth](nodes/13-permissions/README.md) | Classifier gate, least privilege, red-teaming | 1.5d |
| | [14 Reliability](nodes/14-reliability/README.md) | Retries and fallbacks, durable runs, approvals that survive a restart, chaos testing | 1.5d |
| | [15 Cost & latency](nodes/15-cost-latency/README.md) | Cost per resolution, prompt caching, cascades, latency tails, self-hosting math | 1.5d |
| | [16 Frameworks](nodes/16-frameworks/README.md) | Port to Pydantic AI and LangGraph, same graders; persistence vs Node 14 | 1d |
| **VII** | [17 Capstone](nodes/17-capstone/README.md) | Launch: streaming, scorecard + gate, rollout, alerts, runbook | 3.5d |
| Electives | [electives/](electives/README.md) | Computer use, fine-tuning vs harness, sandbox internals, A2A, self-hosting an open model on free compute | |

Roughly 35 working days at full depth. Each node lists its own prerequisites; follow the order.
See [GLOSSARY.md](GLOSSARY.md) for terms used across nodes.

---

## How a node works

```
nodes/NN-slug/
  README.md      the ticket: goal, deliverables, done-when, time boxes, rubric
  TEXTBOOK.md    the theory, condensed; ends with failure modes, self-check, Socratic prompt
  SPEC.md        what your CODING AGENT builds (it reads this file)
  YOU_DO.md      what YOU do by hand. Tags: [AGENT-OFF] [PREDICT] [READ-TRACE] [DECIDE] [LOG]
  CHEATSHEET.md  one page to keep
  tests/         acceptance tests (the grader). Offline and free.
  evals/         live eval cases, where the node has them
  APPENDIX-*.md  dated, version-specific details that will go stale
```

**The loop for every ticket:**
1. `make new-ticket N=NN` (creates branch `node-NN-<you>`).
2. Read `README.md`, then `TEXTBOOK.md`. Answer the self-check before building.
3. Do the `[PREDICT]` and `[DECIDE]` items in `YOU_DO.md` **before** the agent writes code.
4. Write the `[AGENT-OFF]` parts yourself.
5. Hand `SPEC.md` to your coding agent: *"Implement nodes/NN-slug/SPEC.md. Follow AGENTS.md."*
6. Read every line of its diff. Run `make grade N=NN`. Run live evals if the node has them.
7. Fill in the PR template (prediction vs result, explain the diff), push, and let CI grade.

**Why the split between you and the agent?** If the agent writes everything, you finish with
working code and shallow understanding. The `[AGENT-OFF]` parts are the load-bearing ideas of
each node. They are small (usually 30–190 lines) and you write them by hand. Everything around
them is plumbing, and delegating plumbing *is* agentic engineering.

**Stuck?** Each README has time boxes. Past the box, run `make solution N=NN` to merge the
reference solution, read it, and move on. Reading a good solution after a real attempt is
one of the most efficient ways to learn.

---

## Setup (once)

Requirements: macOS or Linux (Windows via WSL2), Python 3.12+, [uv](https://docs.astral.sh/uv/), git.
Recommended: Docker (Node 03 sandbox), Claude Code and/or OpenCode. One API key is enough: an
[OpenRouter](https://openrouter.ai) key gives you free models from three vendors (Node 00 explains the limits).

```bash
make setup         # venv, dependencies, seed DB, creates .env
$EDITOR .env       # add OPENROUTER_API_KEY (ANTHROPIC_API_KEY is optional)
make check-env     # what's ready, which models you get (free or paid), a live test
make check         # Shopfront tests: should be green
```

Then start [Node 00](nodes/00-setup/README.md).

**Budget.** $0 in the default free mode (plus, optionally, $10 of OpenRouter credits bought once to lift the free
daily cap from 50 to 1,000 requests); roughly $40–60 across the course on paid frontier models. Every process has a
hard cap (`COURSE_BUDGET_USD`, default $1.00), and every live command takes `BUDGET=`. **Time in free mode:** the
eval-heavy Nodes 04–06 and the capstone take roughly twice their listed days because of the daily request cap.

---

## Your records
- `LEARNING_LOG.md`: your lab notebook. Each experiment gets *prediction → result → why*.
- `docs/adr/`: Architecture Decision Records. One short file per real design decision.
- These become the raw material for your capstone write-up.

## Repo layout
```
shopfront/   the store app (services, seed data, web UI). FIXTURES.md documents eval fixtures.
agentlab/    YOUR agent code. Grows every node. llm/types.py is the provider-neutral contract.
nodes/       the course
config/      model aliases and prices (models.toml)
scripts/     check_env, check_models, trace_view
data/        generated by `make seed`: shopfront.db (ignored); help_center/, ticket_gold.jsonl, adversarial_index.json (committed)
runs/        generated: traces, cost ledger, eval results (git-ignored)
```
