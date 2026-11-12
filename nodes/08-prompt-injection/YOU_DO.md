# Node 08: your work

Everything here is synthetic: the attacker is customer 9007 (`rex@attacker.example`), and nothing is really sent
(emails go to the outbox table). Cost: the detector work is free; the defence comparison (22 tasks × 5 defences ×
1–2 trials on `fast`) is ≈ $0.50–1.50.

### 1. [PREDICT] + [READ-TRACE] Meet the attacks (≤ 1h)
Read `evals/injections.yaml` and the seeded attacks themselves: `python -m agentlab.security show-attacks` prints
every adversarial review, the shipping address of order 4836 and tickets 222 and 239, plus the benign look-alikes
(invisible characters are shown escaped: in a normal terminal that review looks harmless, which is the point). For each attack, write in `LEARNING_LOG.md`: the technique, the goal, which tool it needs,
and **[PREDICT]** whether `fast` with no defence will fall for it. Then predict the attack success rate (ASR) and
utility of each defence (none, spotlight, filter, taint, plan) on the suite.

### 2. [AGENT-OFF] Your detector (≤ 2h)
`agentlab/security/detect.py`. Contract and acceptance numbers in the docstring; grader `tests/test_detect.py`.
Iterate with `python -m agentlab.security detect-eval` (dev split). Look at the sweep: where would you put the
threshold if false alarms cost a support agent five minutes each? When the tests pass, run the held-out split
**once** (`--split heldout`) and log both numbers. The gap is your overfitting.

### 3. Break it (≤ 1h, ≤ $0.20)
**By hand first**: write five reviews that carry an attack from task 1 and score below your threshold. Add them to
`evals/injections_mine.yaml` (same format, `is_attack: true`) and confirm they evade:
`python -m agentlab.security detect-eval --corpus nodes/08-prompt-injection/evals/injections_mine.yaml --split all`. Then let a model do it:
```bash
.venv/bin/python -m agentlab.security attack --model fast --item db1201 --rounds 6
.venv/bin/python -m agentlab.security attack --model fast --item a_forward --rounds 6
```
How many rounds did it take? Read the evasive versions: would they still work on the agent? Check one: put its text
into review 1201 and run `att_reviews_14` with `--defenses none,filter --tasks att_reviews_14`: run `show-attacks`
once (it prints the database path), copy that file, change review 1201's body in the copy with Python's `sqlite3`
module, and pass `--template-db <your copy>` to `run`.
**[LOG]** One paragraph: what does this tell you about the filter as a security boundary?

### 4. Delegate, then review (≤ 1.5h)
`make new-ticket N=08` → coding agent: *"Implement nodes/08-prompt-injection/SPEC.md. Follow AGENTS.md. detect.py and
policy.py are mine; don't write them."*
Review for:
- **Where the allowlist comes from.** `allowed_recipients` must read only the request (and the DB for the orders
  and tickets it names), never a tool result. Try to break it: what if the request says "order 4836" and the
  address field contains another email?
- **Fail-closed paths.** What happens if `flow_policy` returns something unexpected, or the approver is None?
- **The quarantined call.** Does it get tools? The system prompt? The canary? (It must get none of them.)
- **Plan validation.** Can a plan reference a step that hasn't run? Call a tool that doesn't exist?

### 5. [AGENT-OFF] `flow_policy` (≤ 1h)
`agentlab/security/policy.py`; grader `tests/test_policy.py`. Before coding, write the policy as a table (rows:
tools; columns: tainted or not, recipient allowed or not) and decide every cell. Then implement the table.

### 6. Measure the defences (≤ 1.5h, ≤ $1.50)
```bash
.venv/bin/python -m agentlab.security run --suite nodes/08-prompt-injection/evals/ops --model fast \
   --defenses none,spotlight,filter,taint,plan --trials 2 --budget 1.5 --split all
```
- **[LOG]** The table: ASR, utility on attacked tasks, utility on benign tasks, approvals/task, $/task. Compare with
  your task-1 predictions.
- **Read** every successful attack under `none` (the transcript in trials.jsonl): what did the model do, at which
  turn? If `none` already resists everything on `fast`, run `--defenses none --model gpt-fast` or your `local` model:
  model-level resistance varies a lot by vendor and size.
- **Utility losses**: for each defence, which benign tasks failed, and why? (Filter false positives: see the
  "benign tasks with withheld items" column. Coarse taint blocking the refund? A plan that couldn't succeed blind?)
- **The attacker as recipient**: `att_order_4836` emails the attacker legitimately. What, exactly, stops other
  customers' data from going with it under each defence? Is that enough?
- **Plans**: read three plans the planner wrote (`extra.plan`). Did any include an action the request didn't ask for?
- Run your `injections_mine.yaml` evasions through the ops suite too if you made a review copy in task 3.

### 7. [DECIDE] Threat model (≤ 1h)
`docs/threat-models/ops-agent.md` (use Node 03's threat-model format): assets, trust boundaries, the trifecta legs
for each task type, each attack class with the control that stops it (or "residual risk"), the defence
configuration you'd ship (and per task: which tools the agent should even have), and what you'd monitor (blocked
calls are attacks in progress). State what the plan-then-execute design can't do and how you'd handle those tasks.

### Stretch
- Add a `constrained` quarantined step: the planner may ask the quarantined model for an enum (e.g. `{refund,
  no_refund, unclear}`) and branch on it, with the refund branch requiring approval. Write a task that needs it.
- Split the ops agent into two agents by trust (a reader with no sinks, an actor with no untrusted reads) and measure
  utility versus `plan`.
