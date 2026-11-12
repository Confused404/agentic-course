# Node 06: your work

Cost note: the long suite is quadratic in length (TEXTBOOK §1). One trial of all 12 long tasks with `full` is
roughly 10–15M input tokens; on `fast` that's about $1–1.50 uncached and a fraction of that with caching on. The
50-turn tasks are most of it. So: iterate on `--tags len10,len30`, turn caching on (`opt.cache=true`) on **both**
sides of every comparison, and run `len50` only for decisions. Every experiment re-runs its baseline, so the
`full` side is half your spend. `local` is free and slow; use it for a vendor check, not for iteration.

### 1. [PREDICT] Before anything runs (15 min)
In `LEARNING_LOG.md`, for each long-task kind (`refund_recall`, `constraint`, `constraint_revoked`,
`alias_action`) at 50 turns, predict pass/fail for `full`, `window:4`, `clear:12000:3` and `compact:12000:4`. Then
predict the ranking of the four by **dollars per conversation** with caching on. Write one sentence of reasoning for
the ranking. You'll check both in task 6. Before predicting `constraint_revoked`, read its note in
`evals/long/long.yaml`: under some strategies it passes for the wrong reason. Which ones, and why?

### 2. [AGENT-OFF] `split_for_compaction` (≤ 1h)
`agentlab/context/split.py`. Contract in the docstring; grader `tests/test_split.py`. Before running the tests, draw
(on paper) a history with two customer turns, one of which has three tool rounds, and mark where `keep_turns=1`
cuts. Then check that every case in the tests matches your drawing.

### 3. Delegate, then review (≤ 2h)
`make new-ticket N=06` → coding agent: *"Implement nodes/06-context-memory/SPEC.md. Follow AGENTS.md. split.py,
COMPACTION_PROMPT and memory_policy are mine; don't write them."*
Review for these specifically (they're the bugs that matter here):
- **Copy-on-write.** Does any strategy modify a Message or block it was given? (`ClearToolResults` is the usual
  culprit.) The transcript shares those objects.
- **Transcript vs working history.** Do graders read `transcript`? Does `chat()` store the notes block in history?
  (It must not.)
- **Isolation.** Read every SQL statement in `store.py`. Is `customer_id` in every `WHERE`?
- **Defaults.** `make grade-upto N=06`: nodes 00–05 still green.
- **Fail fast.** `python -m agentlab.evals run ... --context compact:9000` with your prompt still `None` must stop
  before spending anything.

### 4. [READ-TRACE] Baseline: what's in the window, and what a window loses (≤ 1h, ≤ $1)
```bash
.venv/bin/python -m agentlab.evals experiment --suite nodes/06-context-memory/evals/long --model fast \
   --baseline context=full,opt.cache=true --candidate context=window:4,opt.cache=true \
   --tags len10,len30 --trials 1 --budget 1 --log docs/experiments/node06.md \
   --hypothesis "PREDICT: window:4 fails refund_recall, constraint, alias_action at 30 turns; constraint_revoked passes (wrongly)" \
   --change "context full -> window:4"
.venv/bin/python -m agentlab.context report runs/experiments/<ts>
.venv/bin/python -m agentlab.context breakdown runs/experiments/<ts> --task long_constraint_30 --variant baseline
```
`--trials 1` on 8 tasks is a smoke test, not a measurement; the verdict will say so. You're here to read.
- **[LOG]** The breakdown: which component dominates at turn 30? Was the TEXTBOOK §2 table right for this agent?
- **Calibrate the estimate.** In `trials.jsonl` (`extra.turn_stats`), take turns with `calls == 1` (no tool use:
  `input_tokens` is then exactly one request) and compare `est_after` with `input_tokens`. Turns with more calls sum
  several requests, so they'd mislead you. What's the real characters-per-token ratio for this traffic? Is 4.0
  within 20%?
- **Read two failing `window:4` trials.** Find the first turn where the plant was no longer in the window, and what
  the model did at the probe: refuse, ask, guess? Guessing is the dangerous one. Which kind guesses?
- Compare the cache share of the two sides. Explain the number with TEXTBOOK §5, including the minimum cacheable
  length: is the window side's prefix even long enough to be cached?

### 5. [AGENT-OFF] Your `COMPACTION_PROMPT` (≤ 1h)
`agentlab/context/prompts.py`. Write it from TEXTBOOK §4 and what you read in task 4: what would the model have
needed, at the probe, that a summary must therefore keep? Use a structured template. Don't copy the reference from
the solution branch; you'll compare afterwards (escape hatch in README).

### 6. Experiments: one change each (≤ 3h, ≤ $4)
Same rules as Node 05 (hypothesis with a prediction first, one change, trials fixed in advance). Log each to
`docs/experiments/node06.md`. Suggested sequence (each against `full`, caching on both sides, `--tags len10,len30`,
`--trials 2`):
1. `context=clear:12000:3`: does clearing tool results alone keep every plant? (It should: plants are customer
   text.) What does it save?
2. `context=compact:12000:4` with your prompt. Then run `breakdown` on one 30-turn trial of each kind and **read the
   summaries the model saw**. Check `detail` in turn_stats too: "still above trigger" means your summaries plus the
   kept turns don't fit, and you're paying for compactions that barely help. For any failure: was the plant missing from the summary, or present and ignored?
   Change the prompt, re-run, log it as a separate experiment.
3. `context=window:4,notes=on` vs `context=window:4`: can the model's own notes replace a summary? Read the notes
   it wrote (they're in the transcript as `update_case_notes` calls).
4. One run on `--tags len50` for your best two candidates, `--trials 2`. Did the 30-turn ranking hold? Did
   compaction happen more than once, and did facts survive the second round?
Then open `tokens_by_turn.csv` from a `full` vs `compact` run and plot input tokens against turn (a spreadsheet is
fine; or `uv pip install --python .venv matplotlib` and five lines of Python). Check your task-1 predictions: which were wrong, and why?

### 7. [AGENT-OFF] `memory_policy` (≤ 1h)
`agentlab/memory/policy.py`. Rules and order are in the docstring; grader `tests/test_memory_policy.py`.
**[PREDICT]** first: which of the 8 tasks in `evals/memory/memory.yaml` can your policy alone make pass, which
depend on the extraction model, and which on the assistant? Write it down.

### 8. Memory runs and a red-team (≤ 1.5h, ≤ $1)
```bash
.venv/bin/python -m agentlab.evals experiment --suite nodes/06-context-memory/evals/memory --model fast \
   --baseline memory=off --candidate memory=on --trials 3 --budget 1 --log docs/experiments/node06.md \
   --hypothesis "PREDICT: ..." --change "memory off -> on"
```
Read `extra.memory_writes` in `trials.jsonl`: every candidate the extractor proposed (with its evidence quote and
session) and what your policy decided.
- Which tasks fail with memory **on**? For each: extractor (proposed the wrong thing), policy (let it through or
  blocked a good one), or assistant (had the memory and didn't use it)?
- `mem_noise`: how many memories did the extractor propose for a conversation with nothing in it?
- **Red-team your policy.** Add `nodes/06-context-memory/evals/memory/mine.yaml` with three new multi-session tasks
  that try to get something into memory that shouldn't be there (e.g. an authority claim phrased without any of the
  pattern words; a card number spelled out in words; another customer's details). Run them. For anything that gets
  through, decide: extend the policy, change `EXTRACT_SYSTEM`, or accept the risk because code enforces policy
  anyway. Write the reasoning down.

### 9. [DECIDE] ADR 0004 (30 min)
`docs/adr/0004-context-and-memory.md`: the context strategy and thresholds the support assistant ships with, and
whether memory is on. Cite the experiments: success at 30 and 50 turns, dollars per conversation, cache share. State
what you're giving up (which kind of task still fails, and what it would cost to fix), and the memory risks you
accepted. Note anything that behaved differently on another vendor, if you ran one.

### Stretch
- Use the `fast` model as the summariser for a `mid` assistant (`SupportAssistant(summarizer=...)`; add a variant key
  if you want it from the CLI). Does a cheaper summariser lose plants?
- Server-side compaction: read APPENDIX-2026-11 and compare one 50-turn run of the provider's compaction with yours.
