# Ticket LAB-01: Measure how models actually behave before building on them

| | |
|---|---|
| **Estimate** | 2 days |
| **Cost cap** | ≈ $0.80 total across all experiments (each script has its own `--budget`) · Free models: $0 but ≈ 250 requests: fine over a few days at 50/day, or in one sitting with the 1,000/day tier; the scripts pace free calls to OpenRouter's 20-per-minute limit, so expect several minutes per experiment. Without an Anthropic key: E3 (caching) usually shows zero cache reads (free providers rarely report caching: treat it as "what you get without explicit caching"), E4 part B (effort sweep) is skipped, and E6 shows the OpenAI-compatible wire format live while `tests/fixtures/` shows Anthropic's |
| **Prerequisites** | Node 00 |
| **You will touch** | `agentlab/probe/` (new), `LEARNING_LOG.md`, `docs/reports/01-model-behaviour.md` (new) |
| **Done when** | `make grade N=01` green · E0–E6 run on ≥ 2 vendors · report written · your own E7 run |

## Story
Before the founder lets you put a model in front of customers, they ask a fair question: *"What
does this thing actually cost, how fast is it, and how does it fail?"* Vendor marketing won't
answer that. Measurement will. You'll build a small measurement harness and run six experiments
that expose the mechanisms behind cost, latency, caching, randomness, long-context recall and
tool-calling formats. Every later node builds on these results.

## Learning objectives
See TEXTBOOK.md. In short: explain and *predict* tokens, latency (prefill/decode), caching, sampling,
effort, context degradation and wire-format differences, from first-hand measurements.

## Deliverables
1. `agentlab/probe/toy_sampler.py`: **hand-written by you** (AGENT-OFF).
2. `agentlab/probe/` harness: results, parsers, raw callers, haystack builder (your coding agent, from `SPEC.md`).
3. Results of experiments E0–E6 in `runs/node01/` and a LEARNING_LOG entry per experiment
   (prediction → result → why).
4. `docs/reports/01-model-behaviour.md`: a one-to-two page report (template in YOU_DO.md).
5. E7: one experiment of your own design.

## The experiments
| # | Question | Script | Cost |
|---|---|---|---|
| E0 | What do temperature and top-p do to a distribution? | `e0_toy_sampling.py` | free |
| E1 | Does the same text cost the same number of tokens everywhere? | `e1_tokens.py` | < $0.01 |
| E2 | How do input and output length drive latency? | `e2_latency.py` | ~ $0.02 |
| E3 | When does prompt caching hit, what does it save, and what breaks it? | `e3_caching.py` | ~ $0.01 |
| E4 | How do temperature and effort change tool-call accuracy and correctness? | `e4_sampling.py` | ~ $0.08 |
| E5 | Does recall depend on context length, position and distractors? | `e5_needle.py` | ~ $0.15 (`--hard` adds the same again) |
| E6 | What does each vendor send over the wire for the same tool call? | `e6_wire_formats.py` | < $0.01 |

Run them with `.venv/bin/python nodes/01-llm-internals/experiments/eN_*.py --help` to see options
(`--models`, `--budget`, `--trials`, `--fresh`). Results **append** to `runs/node01/eN_*.jsonl` so you
can re-run one model without losing the others. Pass `--fresh` to start over. Each run is one trace
(`make trace`). E1 downloads a tokenizer file the first time (needs internet).

## Time boxes
| Step | Box | If you blow through it |
|---|---|---|
| Read TEXTBOOK + self-check | 2h | |
| toy_sampler by hand | 1.5h | read the reference in `solution/node-01`, then rewrite it from memory |
| Coding agent builds the harness | 1.5h incl. your review | `make solution N=01` (it also contains a reference `toy_sampler.py`: keep yours with `git checkout --ours agentlab/probe/toy_sampler.py`) |
| Experiments E0–E6 + log entries | 4h | run on 2 vendors instead of 3 |
| Report | 1h | |
| E7 | 2h | skip; note what you'd have tested |

## Rubric (self-review; 0–2 each)
| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Sampler | doesn't pass tests | passes | passes, and you can explain why top-p keeps "the smallest sufficient set" and why subtracting the max is safe |
| Predictions | written after running | written before, vague | written before, quantitative, with confidence |
| Explanations | "model X is faster" | mechanism named | mechanism named *and* checked with a second measurement |
| Report | missing | descriptive | contains rules you'll actually follow in later nodes |
| Cost discipline | over a cap | within caps | within caps, and you can say what each experiment cost |

## Files
`TEXTBOOK.md` · `SPEC.md` (for your coding agent) · `YOU_DO.md` · `CHEATSHEET.md` · `APPENDIX-2026-11.md` · `experiments/` · `tests/`
