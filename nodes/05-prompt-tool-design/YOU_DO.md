# Node 05: your work

### 1. [READ-TRACE] Failure analysis → hypotheses (≤ 1h)
From your Node 04 report (`runs/evals/<ts>/report.md`, "Failures to read"), read at least **five** failing trials for
your chosen default model (ADR 0002). For each, log: task, failure class (selection / arguments / interpretation /
environment / grader / task), the *exact* moment it went wrong (which turn, which tool result), and a hypothesis of
the form *"because the model sees X, it does Y; changing X to X' should make it do Z."* Rank the hypotheses by
(how many tasks they'd affect) × (how confident you are).

### 2. [AGENT-OFF] Write the tool design: `docs/design/support-tools-v2.md` (≤ 1.5h)
Constraints (the eval suite depends on them): keep every v1 tool name and parameter name; no new required
parameters; policy stays in `shopfront/services.py`. Within that, redesign everything the model *reads*:
```
## Why a v2            (your failure analysis, briefly)
## Constraints
## Tools               for each: exact description text; each parameter's description (with an example);
                       the return shape (which derived fields? dollars as well as cents?)
## Errors              a table: code → message → next_steps (what should the model do next?)
```
Run `python -m agentlab.evals lint --tools v1` first to see what the lint flags in v1. Put each description and
parameter description in the doc **exactly as the model will read it** (a fenced YAML block per tool works well):
`test_tools_v2.py` checks that every v2 string appears verbatim in your doc. Tag each part of the design with the
feature it belongs to (`desc`, `errors`, `returns`), because task 4 tests them one at a time.

### 3. Delegate, then review (≤ 1.5h)
`make new-ticket N=05` → coding agent: *"Implement nodes/05-prompt-tool-design/SPEC.md. Follow AGENTS.md. Implement
docs/design/support-tools-v2.md exactly; don't write SYSTEM_PROMPT_V2."*
Review: does `make_support_tools(..., variant="v2")` match your document *word for word*? Run
`python -m agentlab.evals lint --tools v2`: zero findings. Check `v1+desc`, `v1+errors` and `v1+returns` each change
only their part (`lint --tools v1+desc` should clear the description warnings and nothing else). `test_tools_v2.py` runs the whole Node 04 suite's golden
scripts with your v2 tools. If one fails, your design broke an interface the evals depend on.

### 4. [AGENT-OFF] Experiments, one change each (≤ 4h of work, ≤ $3)
Budget wall-clock time too: one experiment at 3 trials over a 10-task slice is 60 conversations, typically 5–15
minutes on a hosted model and longer locally. Expect 6–10 experiments in this task, not 30.

You'll build `SYSTEM_PROMPT_V2` incrementally. Register intermediate versions so each experiment changes one thing:
```python
# agentlab/assistant/prompts.py (your text)
PROMPTS["v1-reasons"] = SYSTEM_PROMPT_V1 + "\n\nRefund reasons: ..."   # one change
```
`SYSTEM_PROMPT_V1` has `{today}` near the top (the lint's `volatile-early` warning). Moving it to the end is itself
a legitimate first experiment; don't let v2 inherit it by accident.

Tools are split the same way: test `tools=v1+desc`, `v1+errors`, `v1+returns` one at a time against `tools=v1`
rather than jumping straight to `v2`. Then, for each hypothesis (most promising first):
```bash
.venv/bin/python -m agentlab.evals experiment --suite nodes/04-evals/evals/support --model fast \
   --baseline prompt=v1,tools=v1 --candidate prompt=v1,tools=v1+desc --tags refund --trials 3 --budget 0.6 \
   --hypothesis "PREDICT +10: reason descriptions fix damaged/changed_mind confusion; 10 tasks x 3 trials" \
   --change "tools v1 -> v1+desc"
```
Use **one** tag per focused run (the tag where the failure lives); the slice needs ≥ 8 tasks or the verdict is
`insufficient`. If a slice is thinner, add tasks to the suite first (Node 04 task 2) or widen to two related tags.
Model options are variables too: `--candidate prompt=v1,tools=v1,opt.effort="low"`.

Rules:
- **[PREDICT]** the diff, the tasks and the trials *before* each run, in `--hypothesis`. Don't add trials after
  looking (TEXTBOOK §6, peeking).
- One change per experiment. The baseline for experiment *n* is the accepted state after experiment *n−1*.
- Acceptance rule: the slice run says `better`, **and** a full dev run (no `--tags`, `--split dev`) says
  `better` or `non-inferior`. `inconclusive` on the full run means "can't rule out a regression": don't accept yet.
- Record the outcome with `--decision keep|revert|retest` (or edit the row afterwards). The log stores both variants'
  content hashes, so later you can tell which exact text a row refers to.
- Do at least one experiment you expect to *fail* (e.g. ALL-CAPS emphasis, or a few-shot example), and one on a
  **different vendor** (`--model gpt-fast` or `local`) to see whether a change transfers.
- A single `better` among many experiments may be noise (one in twenty is, at 95%). Re-test anything marginal.
When done, set `SYSTEM_PROMPT_V2` to the accumulated accepted text. `test_prompt_v2.py` checks it's lint-clean.

### 5. Final checkpoint: once (≤ 30 min, ≤ $1)
```bash
.venv/bin/python -m agentlab.evals experiment --suite nodes/04-evals/evals/support --model fast \
   --baseline prompt=v1,tools=v1 --candidate prompt=v2,tools=v2 --split all --trials 3 --budget 1 \
   --change "FINAL v1 -> v2 (dev + heldout)"
```
The output has a by-split table: compare the **held-out** diff with the dev diff. The gap estimates how much you
tuned to the dev set. Held-out alone has 7 tasks, so its own verdict will read `insufficient`; that's the honest
answer (it can only reveal large gaps), and why the point estimates and per-task results are what you compare here.
(To look at held-out by itself: `--split heldout`.) Run this **once**.

### 6. [DECIDE] ADR 0003 (30 min)
`docs/adr/0003-prompt-and-tools-v2.md`: for each paragraph of your prompt and each changed tool description, cite the
experiment that justifies it. List the lines with no evidence and decide whether to keep or delete them. Note any
vendor-specific behaviour you saw.
