# Ticket CONTEXT-06: Long conversations and returning customers

| | |
|---|---|
| **Estimate** | 2–2.5 days (long-conversation runs take wall-clock time: a 50-turn task is ~100 model calls) |
| **Cost cap** | ≈ $6 (baseline ≈ $1, strategy experiments ≈ $4, memory ≈ $1; iterate on `len10,len30` with caching on) · Free models: $0 but ≈ 1,000+ requests (long conversations are many turns): the 1,000/day tier; iterate on `len10` first |
| **Prerequisites** | Node 04 (harness, state graders), Node 05 (experiment runner, one-change discipline) |
| **You will touch** | `split.py`, `COMPACTION_PROMPT`, `memory_policy` (yours); strategies, memory store, sessions in the harness (agent); `docs/experiments/node06.md`, `evals/memory/mine.yaml`, `docs/adr/0004-*` |
| **Done when** | `make grade N=06` green · baseline + ≥ 4 logged experiments incl. one at 50 turns · memory run + 3 red-team tasks · ADR 0004 |

## Story
Customers don't have 3-turn conversations. Some chat for an hour, and some come back next week expecting you to
remember them. Right now the assistant sends its entire history on every call, so cost grows quadratically, and it
forgets everything between sessions. You'll measure where it breaks, then fix it: decide what the model sees on each
call (sliding windows, clearing tool results, compaction, notes), and what it keeps between conversations (memory),
without leaking or poisoning anything.

## Deliverables
1. `agentlab/context/split.py::split_for_compaction`: **by hand** (AGENT-OFF). Every strategy depends on the cut
   being exactly right.
2. `agentlab/context/prompts.py::COMPACTION_PROMPT`: **your** prompt (AGENT-OFF), from the failures you read.
3. `agentlab/memory/policy.py::memory_policy`: **by hand** (AGENT-OFF). What may enter long-term memory.
4. Context strategies, token estimates, memory store/extraction/forgetting, multi-session evals, context report:
   coding agent, from `SPEC.md`.
5. `docs/experiments/node06.md`: a `full` vs `window` baseline and ≥ 4 single-change experiments, one at 50 turns.
6. `evals/memory/mine.yaml`: three red-team memory tasks against your own policy.
7. `docs/adr/0004-context-and-memory.md`: the strategy, thresholds and memory mode you ship, with costs.

## Time boxes
| Step | Box | Escape hatch |
|---|---|---|
| TEXTBOOK + predictions | 2h | |
| `split_for_compaction` | 1h | `git show solution/node-06:agentlab/context/split.py`, then rewrite it yourself |
| Agent builds SPEC + review | 2h | `make solution N=06` |
| Baseline + reading traces | 1h | |
| Compaction prompt | 1h | after your own attempt: `git show solution/node-06:agentlab/context/prompts.py`; diff the reasoning |
| Experiments | 3h | three experiments instead of four; skip notes |
| `memory_policy` + memory runs + red-team | 2.5h | red-team two tasks instead of three |
| ADR | 0.5h | |

## Rubric (0–2 each)
| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Cutting | split breaks tool pairs | tests pass | tests pass, and you can explain each contract item from a provider error it prevents |
| Reading | numbers only | read failures | located the turn each plant was lost and classified the failures (missing vs present-but-ignored) |
| Compaction prompt | generic "summarise" | template | template whose sections each trace to a failure you read |
| Cost reasoning | tokens only | tokens and dollars | dollars, cache share and the tokens-by-turn curve explained with TEXTBOOK §5 |
| Memory safety | policy tests pass | + memory suite read | + red-team tasks, and a written decision for each gap |
| Decision | "compaction is best" | strategy + evidence | strategy, thresholds, costs, and what still fails, with the price of fixing it |
