# Node 10: your work

Cost: the main comparison on `fast` (5 tasks × 3 architectures) is ≈ $0.10–0.30; the `mid` runs ≈ $0.30–0.50.
`python -m agentlab.multi tasks` is free. On free OpenRouter models, read the README's request budget first.

### 1. [PREDICT] (20 min)
Run `python -m agentlab.multi tasks` and read the five questions and gold answers. Then read `agentlab/multi/tools.py`
(GIVEN): what can each tool see, and how many calls does one category need? In `LEARNING_LOG.md`, predict for each
architecture on `fast`: how many of the 5 tasks it gets right, tokens per task relative to `single`, and which task
each is most likely to fail and why. Commit the prediction before running anything.

### 2. [AGENT-OFF] reconcile (≤ 1h)
`agentlab/multi/reconcile.py`; grader `tests/test_reconcile.py`. Read the contract twice; work out
`test_last_report_per_shard_wins` and `test_duplicates_and_conflicts` on paper first. Then answer in the log: for
each rule in the contract, what would go wrong downstream if it were missing?

### 3. Delegate, then review (≤ 2h)
`make new-ticket N=10` → coding agent: *"Implement nodes/10-multi-agent/SPEC.md. Follow AGENTS.md. reconcile.py is
mine; don't write it."*
Review for:
- **Isolation**: what exactly is in a worker's first prompt? (`test_orchestrator_isolated_parallel_workers` checks
  the minimum; read `run_worker`.)
- **Parallelism**: are workers started together, and does one worker's crash leave the others running?
- **Honesty**: does `delegate` tell the lead what's still missing? Can the orchestrator answer while shards are
  missing, and does the result record it?
- **Accounting**: is every model call metered, including the reducer and retried workers?

### 4. The comparison (≤ 2h, ≤ $0.60)
```bash
.venv/bin/python -m agentlab.multi run --budget 0.3 --archs single:fast,orch:fast:fast,mapreduce:fast:fast
.venv/bin/python -m agentlab.multi report runs/multi/<ts>
.venv/bin/python -m agentlab.multi run --budget 0.5 --archs single:mid,orch:mid:fast --tasks lowest_rated_per_category,category_ratings,restock
```
- **[LOG]** both tables against your predictions. Where were you wrong?
- For every failed trial, run `show` and find the agent and the step where it went wrong. Classify each failure:
  *coverage* (a category skipped), *definition* (wrong threshold, rounding, window), *combination* (average of
  averages), *format* (answer shape), *coordination* (missing shard ignored, duplicate work). Which architecture
  fails in which way?
- Read three worker briefs the lead wrote. Do they state the definitions? Do they ask for combinable fields?
- **Peak prompt**: how much smaller is the orchestrator's largest prompt than the single agent's? Is that the
  number that matters here, given these context sizes?
- **Tokens by role**: is the lead or the workers spending the tokens?

### 5. [LOG] The brief experiment (≤ 45 min)
Pick the orchestrator's worst failure. Change ONE thing in `LEAD_SYSTEM` (your coding agent wrote it: you own it
now), predict the effect, and re-run that task with `--trials 3` for both versions, labelling them so one report can
compare them:
```bash
.venv/bin/python -m agentlab.multi run --archs orch:fast:fast@before --tasks <task> --trials 3   # before the edit
.venv/bin/python -m agentlab.multi run --archs orch:fast:fast@after  --tasks <task> --trials 3   # after
.venv/bin/python -m agentlab.multi report runs/multi/<ts1> runs/multi/<ts2> --a orch:fast:fast@before --b orch:fast:fast@after
```
Log it as a Node 05 experiment. With 3 trials on one task, what difference could you actually detect?

### 6. [DECIDE] The tool experiment (≤ 45 min)
Add a tool `category_summary(category)` returning, for each product in the category, the same fields as
`product_stats` (one call per category): put it in a new `agentlab/multi/coarse.py` (don't edit the GIVEN
`tools.py`), and add an architecture `single_coarse:A` to `parse_arch`/`run_arch` that runs `run_single` with
`analytics_tools(conn) + [category_summary]`. Before running: predict what happens to the single agent's accuracy,
tokens and wall time, and to the case for multiple agents. Run the five tasks for `single:fast,single_coarse:fast`. **[LOG]** Then: what does this say about when multi-agent systems are the right fix, and
when the real problem is tool granularity (Node 05)?

### 7. [DECIDE] ADR 0007 (30 min)
`docs/adr/0007-multi-agent.md`: which architecture would you ship for this assistant, with accuracy, tokens per
task, the token multiple, p50 wall time and the failure modes you saw, all from your runs. What would make you
switch to an orchestrator (be specific: catalogue size, question types, latency need)? Which agents, if any, may
ever have write tools?

### Stretch
- Let the lead also call `product_stats` (spot-checking a worker). Does it verify, or just redo the work?
- Put a prompt-injected review on a low-rated product (Node 08's attacker account) and ask a question whose workers
  read reviews. None of the five tasks needs reviews, and `run` seeds a fresh database each time, so you'll add the
  review in `shopfront/seed.py` (or in a copy of the run's database) and add a task to `TASKS`. What can the
  injection change, and what can't it?
- Run the same comparison through your coding agent's own subagents (APPENDIX): ask it to answer one task with and
  without subagents, and compare the token counts it reports.
