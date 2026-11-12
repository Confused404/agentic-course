# Ticket PROMPT-05: Improve the assistant one measured change at a time

| | |
|---|---|
| **Estimate** | 1.5–2 days (experiments take wall-clock time: ~5–15 min each on a hosted model) |
| **Cost cap** | ≈ $4 (4–6 focused experiments ≈ $0.20–0.50 each on `fast`, a vendor check, one final dev + held-out run) · Free models: $0 but ≈ 500–800 requests: the 1,000/day tier, one or two experiments a day |
| **Prerequisites** | Node 04 (harness, stats, a baseline report) |
| **You will touch** | `docs/design/support-tools-v2.md` + `SYSTEM_PROMPT_V2` (yours), lint/variants/experiment runner (agent), `docs/experiments/node05.md`, `docs/adr/0003-*` |
| **Done when** | `make grade N=05` green · ≥ 4 logged single-change experiments (tool features tested separately) · final dev + held-out comparison · ADR 0003 |

## Story
Node 04 told you *where* the assistant fails. The tempting move is to rewrite the prompt in one sitting, add three
"IMPORTANT"s and declare victory. Instead you'll run it like engineering: read the failures, form hypotheses, change
one thing (a tool description, an error message, one paragraph of the prompt), measure it against the baseline on the
same tasks, and keep a log. At the end you check the held-out tasks once, to see how much of your gain was real.

## Deliverables
1. `docs/design/support-tools-v2.md`: **your** tool redesign (descriptions, parameter docs, return shapes, error
   messages with next steps), grounded in Node 04 failures (AGENT-OFF: it's a design document, and the design is the skill).
2. `SYSTEM_PROMPT_V2` in `agentlab/assistant/prompts.py`: **your** prompt (AGENT-OFF), built from accepted experiments.
3. Tool/prompt lint, tool variants `v2` and `v1+desc|errors|returns` (implementing your document), experiment runner
   (paired, interleaved, non-inferiority verdicts, hashed log) and CLI: coding agent, from `SPEC.md`.
4. `docs/experiments/node05.md`: ≥ 4 experiments, each a single change with hypothesis, interval and decision.
5. `docs/adr/0003-prompt-and-tools-v2.md`: what you shipped, the evidence for each part, the held-out result.

## Time boxes
| Step | Box | Escape hatch |
|---|---|---|
| TEXTBOOK + failure analysis | 2h | |
| Tool design doc | 1.5h | read the reference doc on `solution/node-05` *after* writing yours, and diff the reasoning |
| Agent builds SPEC + review | 1.5h | `make solution N=05` |
| Experiments | 4h | 3 experiments instead of 4–6 |
| Final checkpoint + ADR | 1h | |

## Rubric (0–2 each)
| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Hypotheses | changes without reasons | reasons after the fact | written before each run, tied to a classified failure |
| Discipline | many changes per run | one change per run | one change per run, plus a full-suite `non-inferior` check before accepting |
| Statistics | point estimates | intervals | intervals; trials fixed before running; inconclusive and insufficient treated as such |
| Overfitting | held-out never run | run once | run once, and the dev/held-out gap is discussed honestly |
| Design quality | v2 lint dirty | lint clean | lint clean, and every error message names a next step the model actually takes in traces |
