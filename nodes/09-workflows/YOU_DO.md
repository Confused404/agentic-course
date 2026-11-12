# Node 09: your work

Cost: rules are free; one LLM call per ticket on `fast` is a fraction of a cent. The full comparison on the dev split
(160 tickets × rules, llm:fast, llm:mid, vote×5, cascade, agent) is ≈ $0.30–0.60. Drafting six tickets with a critic loop is a few
cents.

### 1. [PREDICT] (20 min)
Read twenty tickets: `python -c "import sqlite3; [print(r) for r in sqlite3.connect('data/shopfront.db').execute('SELECT id, body FROM tickets WHERE id IN (1,2,3,40,80,120,160,200,211,212,215,216,217,222,226,229,231,232,235,240)')]"`
and their gold labels in `data/ticket_gold.jsonl`. Then predict in `LEARNING_LOG.md`: what coverage and precision will
hand-written rules get on easy tickets? What accuracy will `llm:fast` get on hard ones? How much cheaper will the
cascade be than `llm:mid` on everything, and at what accuracy cost?

### 2. [AGENT-OFF] Rules (≤ 1.5h)
`agentlab/workflows/rules.py`; grader `tests/test_rules.py`. Precision first: write a rule only when you'd bet on
it. Run the tests often; read every ticket a rule gets wrong. When the tests pass, check the held-out split once:
```bash
.venv/bin/python -m agentlab.workflows triage --methods rules --split heldout
```
**[LOG]** dev vs held-out coverage and precision. Your rules were fitted to dev; how much did that cost? If the
two are nearly equal, ask why: held-out easy tickets come from the same templates as dev. What does a held-out set
drawn from the same distribution NOT tell you about next month's tickets? Write three new phrasings of common
requests yourself and run your rules on them.

### 3. Delegate, then review (≤ 1.5h)
`make new-ticket N=09` → coding agent: *"Implement nodes/09-workflows/SPEC.md. Follow AGENTS.md. rules.py and
selective.py are mine; don't write them."*
Review for: unparseable output never becoming a label; votes running in parallel (time one `vote:fast:5` against
one `llm:fast`); the cascade counting the cheap stage's cost when it escalates; the agent baseline failing honestly
when it never calls `set_triage`.

### 4. [AGENT-OFF] Selective prediction (≤ 45 min)
`agentlab/workflows/selective.py`; grader `tests/test_selective.py`. Work the test's expected values out on paper
first.

### 5. The comparison (≤ 2h, ≤ $0.60)
```bash
.venv/bin/python -m agentlab.workflows triage --split dev --budget 0.6 \
   --methods rules,llm:fast,llm:mid,vote:fast:5,cascade:fast:5:0.8:mid,agent:fast
.venv/bin/python -m agentlab.workflows report runs/workflows/<ts> --a llm:mid --b cascade:fast:5:0.8:mid
```
- **[LOG]** The table. Which method would you ship, at what cost per 1,000 tickets?
- **Stages**: what share of tickets did each cascade stage decide? Did that match your task-1 prediction?
- **Confusions**: read the top three confusions for `llm:fast`. Are they model errors or category-definition
  problems? Change one line of `TRIAGE_SYSTEM` (your coding agent will have written it: you own it now) for the worst
  one, re-run on `--hard-only`, and log it as a Node 05-style experiment (one change, prediction first).
- **Confidence**: is vote agreement a useful signal? Look at the coverage line in the report: what threshold gives
  95% accuracy, and what coverage does that leave? Then check that threshold on the held-out split.
- **Agent**: read three `agent:fast` transcripts. Did the order lookup ever change the label? What did the agent cost
  per ticket compared with the cascade?
- **Injection**: what did each method do with ticket 239 (in dev)? Ticket 222 is its held-out sibling: check it
  with `--split heldout --hard-only`.

### 6. Evaluator-optimizer (≤ 1h, ≤ $0.20)
```bash
.venv/bin/python -m agentlab.workflows draft --writer fast --critic mid --tickets 211,212,216,217,226,232
```
Read every round. **[LOG]** For how many tickets did round 2 improve on round 1 by your own judgment? Did the critic
ever demand something unreasonable? Would you ship drafts without the critic, with it, or not at all?

### 7. [DECIDE] ADR 0006 (30 min)
`docs/adr/0006-ticket-triage.md`: the triage design you'd ship (stages, models, threshold, the human queue), with
accuracy at the threshold, coverage, cost per 1,000 tickets and p95 latency, all from your runs. What would make you
switch to an agent, and what would make you drop the LLM entirely?

### Stretch
- Add a sectioning step that runs your Node 08 detector in parallel with classification, and send flagged tickets
  straight to the human queue.
- Run the dev comparison on the provider's batch API (APPENDIX) and compare cost.
