# Node 04: your work

### 1. [PREDICT] (15 min)
Read the suite (`evals/support/*.yaml`). For each of `fast`, `gpt-fast`, `local`, predict the dev-split pass rate, the
pass^3, and the weakest tag. Which task do you think is hardest overall? Log it.

### 2. [AGENT-OFF] `stats.py` (≤ 1.5h)
Implement the five functions in `agentlab/evals/stats.py` (contracts in the docstring; grader
`tests/test_stats.py`). Before running the tests, compute by hand (paper or REPL with only `math`):
- the Wilson interval for 8/10;
- pass^3 for a task that passed 9 of 10 trials, and why it isn't 0.9³.
Log both.

### 3. Delegate and review (≤ 3h)
`make new-ticket N=04` → coding agent: *"Implement nodes/04-evals/SPEC.md. Follow AGENTS.md. stats.py is mine; don't
edit the suite."*
Review checklist:
- [ ] `graders.py`: find the line that makes `refund: issued` ignore the refund that order 4828 had *before* the trial.
- [ ] `runner.py`: what happens to a half-finished run if your laptop sleeps? (Hint: `trials.jsonl` is appended per trial.)
- [ ] `test_suite_tier1.py` is green: every golden script passes, every bad script fails. Pick one bad script and
      explain which grader catches it.
- [ ] `report.py` calls *your* stats functions. Nothing re-implements them.

### 4. Live matrix + [READ-TRACE] (≤ 3h, ≤ $3)
```bash
.venv/bin/python -m agentlab.evals run --suite nodes/04-evals/evals/support --models fast,gpt-fast,local --trials 3 --budget 3
```
(or `make eval N=04 BUDGET=3`). Open `runs/evals/<ts>/report.md`. Then:
- Compare with your predictions.
- Read **three failures** end to end (`transcript` in `trials.jsonl`, or the trace). Classify each (selection /
  arguments / interpretation / environment / **grader bug** / **task bug**).
- Read **two passes** too: do you agree they passed?
- Run `python -m agentlab.evals compare runs/evals/<ts> --a fast --b gpt-fast`. Does the CI exclude 0?

### 5. Calibrate the judge (≤ 1.5h)
```bash
.venv/bin/python nodes/04-evals/judge_calibration.py runs/evals/<ts>
```
Label at least 20 judged trials blind, **including at least ~8 you consider failures** (use `--max` and skip easy passes;
if the run has too few failures, label trials from `local`). Log the agreement, **Cohen's κ** and the **judge's recall
on your failures** (the script prints all three), and compute the Wilson interval of the agreement with *your*
`wilson_interval`: what can 20 labels actually certify? For each disagreement, decide who was right and why: rubric
ambiguity? missing evidence? judge leniency? If κ is under ~0.6 or failure recall is low, propose a better rubric in
your log (the suite files are the course's; put your improved rubric in `mine.yaml` as a new task).
Note: the judge (`gpt-mid` in `[evals]`) may share a vendor or even a model with one of the models it grades
(`make check-env` shows what each alias means). With an Anthropic key it's OpenAI-family and also grades `gpt-fast`:
re-run the judged tasks with `--judge open-hosted`. In free mode it's the same gemma model as `local`: check whether
`local`'s judged tasks look suspiciously good (self-preference), and re-run them with `--judge gpt-fast`.

### 6. [DECIDE] ADR 0002: the default model (30 min)
`docs/adr/0002-default-model.md`: which model should the support assistant use? **Before opening the report**, write
down your primary comparison (e.g. "`fast` vs `gpt-fast` on task mean") and the threshold that would change your
mind (TEXTBOOK §4, many comparisons). Then use the task mean with its CI, pass^3 with its CI, cost per pass and the
Pareto set. Treat the per-tag table as exploratory. State the condition that would make you revisit the decision.

### 7. Grow the suite from reality (≤ 1.5h)
1. `ASSISTANT_MODEL=<your choice> make run` and have 10+ conversations as different customers (9001–9006), including
   odd ones: multi-intent, typos, other languages, pushy customers, vague questions.
2. `python -m agentlab.evals mine --out nodes/04-evals/scratch/candidates.yaml`.
3. Turn at least three candidates into real tasks in `evals/support/mine.yaml`, each with **graders, a golden script
   and a bad script**. `make grade N=04` (Tier 1) must stay green.

### 8. Measure your own noise (30 min, ≤ $1)
Re-run the matrix for **one** model with the same settings an hour later. Compare that model across the two runs:
`python -m agentlab.evals compare RUN_A RUN_B --model fast`. How big is the run-to-run difference compared with the
model-to-model difference? Log it. This is your personal "infrastructure noise" number.
