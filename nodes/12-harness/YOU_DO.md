# Node 12: your work

Cost: the tests, `new` and `accept` are free. The ablation on `fast` is ≈ $0.60; cross-model ≈ $1–1.50 more.

### 1. [PREDICT] (30 min)
Read `nodes/12-harness/project_template/` (BACKLOG.md, AGENTS.md, the code, the skill) and skim the acceptance tests
in `nodes/12-harness/acceptance/` (the agent never sees these). In `LEARNING_LOG.md`, predict for `fast`: features
accepted and overclaims for each of `single`, `loop`, `loop+verify`, `loop+verify+eval`, `full`; which feature fails most; and what
`full` costs relative to `loop+verify`.

### 2. [AGENT-OFF] progress.py (≤ 1.5h)
`next_feature`, `validate_update`, `record_attempt`, `stalled`; grader `tests/test_progress.py`. For
`validate_update`, list every way an agent could corrupt the progress file to look better, then check each is a
problem in your code.

### 3. Delegate, then review (≤ 3h)
`make new-ticket N=12` → coding agent: *"Implement nodes/12-harness/SPEC.md. Follow AGENTS.md. progress.py is mine;
don't write it."*
Review for: the agent's progress edits validated after EVERY session; failed attempts reset to the last good
commit; the evaluator has no write tools and fails closed; the stop hook capped and sharing the session's turn
budget; `ProjectGate` allowing new test files but not the original ones; tests run with `python -I` so a workspace
`pytest.py` can't forge results. Then ask: what in the session COULD still reach `nodes/12-harness/acceptance/`
(hint: the local sandbox and the editable install), and how does the harness notice?

### 4. The ablation (≤ 2.5h, ≤ $0.60)
```bash
.venv/bin/python -m agentlab.harness run --configs single,loop,loop+verify,loop+verify+eval,full --models fast --budget 1.2
.venv/bin/python -m agentlab.harness show runs/harness/<ts>/ws-loop-fast-0
```
- **[LOG]** the table next to your prediction.
- For each config, open its workspace: `git log --oneline`, `features.json`, the tests the agent wrote, and
  `.harness-result.json` events. Explain every overclaim: what did the agent's tests check, and what did the hidden
  test catch?
- Did any session try to edit the progress file illegally, or a protected file? What stopped it?
- `loop+verify+eval` vs `loop+verify`: what did the evaluator reject, and was it right? Read one rejection's notes
  and the next session's fix. Then `full` vs `loop+verify+eval`: what did hooks and the skill add on top?
- The "skill loads" column counts `load_skill` calls. Did the skill get used, and did features improve where it
  was? Check the "stop" column too: a run cut short by the budget isn't a result.

### 5. Cross-model (≤ 1h, ≤ $1.50)
```bash
.venv/bin/python -m agentlab.harness run --configs single,full --models fast,gpt-fast,open-hosted --budget 2
```
**[LOG]** Which harness pieces matter more for which model? Is there a model for which `full` adds nothing?

### 6. [DECIDE] The same backlog in a coding agent (≤ 2h)
```bash
.venv/bin/python -m agentlab.harness new /tmp/promo-cc
cd /tmp/promo-cc && git log --oneline
```
In that workspace (outside the course repo, so the agent can't easily find the acceptance tests), give Claude Code
or OpenCode the backlog in fresh sessions, one feature per session (the LOOP_TASK idea, by hand or in a shell loop).
The workspace has no virtualenv of its own: use the course venv's Python by absolute path everywhere (in prompts,
hooks and AGENTS.md), e.g. `/path/to/agentic-course/.venv/bin/python -m pytest -q`.
Add, in the **workspace's local settings only** (never the course repo's):
- a **stop hook** that runs the tests with that Python and refuses to stop while they're red (APPENDIX: Claude
  Code's Stop hook with exit code 2, checking `stop_hook_active` so it can't loop forever; or an OpenCode plugin);
- a **pre-tool hook** that blocks edits to `tests/test_engine.py`;
- the project's skill (`skills/promo-testing/SKILL.md` copied to where your agent looks for skills).
Then score it: `.venv/bin/python -m agentlab.harness accept /tmp/promo-cc` (run from the course repo).
**[LOG]** accepted features, rough cost/time, and how each hook or skill behaved (did the stop hook fire? did the
skill get loaded?). How does it compare with your `full` config?

### 7. [DECIDE] ADR 0009 (30 min)
`docs/adr/0009-harness.md`: the configuration you'd run unattended overnight, for each model you tried; the
overclaim rate you measured and what human review that implies; which pieces you'd drop on a stronger model, and the
measurement that would tell you to.

### Stretch
- An **initializer** session: give the agent only BACKLOG.md and have it write `features.json` itself (finer-grained
  features, each with a test idea). Does a finer list change acceptance?
- Make the evaluator a different vendor's model (`--evaluator-model gpt-mid`). Correlated blind spots?
- Add a context-pressure check: end a session early (with a handoff note in `features.json`) when its prompt
  exceeds N tokens (Node 06).
