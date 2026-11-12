# Node 12 TEXTBOOK: Harness engineering: getting long work out of coding agents, reliably

> Vendor-neutral. Claude Code's and OpenCode's hooks, skills and settings live in `APPENDIX-2026-11.md`.

## Learning objectives
By the end you can:
1. Name the failure modes of one long agent session on a multi-feature backlog, and the harness piece that
   addresses each.
2. Move the agent's state out of its context window (progress file, git checkpoints, fresh sessions) and keep that
   state honest when the agent is the one editing it.
3. Separate "the agent says it's done" from "it's done": harness-run checks, hidden acceptance tests, and a
   separate skeptical evaluator.
4. Use hooks for rules that must always hold, and skills for knowledge that's only sometimes needed.
5. Run an ablation that measures what each harness piece buys, per model, and decide which pieces to keep.

---

## §1 The harness is everything but the model

A **harness** is the code and files around a model that turn it into a worker: the loop (Node 02), the tools and
their gate (Node 03), the context policy (Node 06), and, for long work, the pieces this node adds: where state
lives between sessions, who decides that something is done, what's checked automatically, and what knowledge is
loaded when. Claude Code and OpenCode are harnesses; so is your `shopdev`, and so is the ten-line shell loop some
people run them in.

Why it matters: on the same model, harness changes can move results more than a model upgrade. And the reverse also
holds: when a stronger model arrives, pieces that compensated for the old one's weaknesses become dead weight
(extra calls, extra tokens, extra latency). A harness is a set of hypotheses about the model's failure modes, and
each one should be re-measured, not assumed (§7).

---

## §2 The baseline: one long session

Give an agent the whole backlog ("implement F1 to F5") in one session and watch for:
- **Premature "done".** It stops after three features, or declares victory with failing tests.
- **Self-evaluation bias.** Asked whether its own work is good, a model tends to say yes. A feature it marked
  "passing" is a claim, and claims are cheap.
- **Context exhaustion and drift.** Tool output piles up (Node 06); by feature 4, the spec for feature 1 is far
  behind and the agent's picture of the code is stale.
- **Collateral damage.** Under pressure to make tests pass, agents edit the tests (Node 03 §3).
- **No recovery point.** A failure at feature 4 leaves features 1-3 tangled with half-done 4.

None of this means the model is bad. It means the harness gave it one context window, no external memory, and
its own word as the only check.

---

## §3 State outside the context window

The fix that keeps reappearing in long-running harnesses: **each session starts fresh and reads its state from
files**, like an engineer starting a shift.

- A **progress file** (`features.json`): the backlog, each item's status, attempt count and notes for the next
  session. Structured (JSON), because models edit Markdown checklists loosely.
- **Git as the log and the undo button.** Commit after every session that passed; a failed attempt is reset to the
  last good commit, so the next session starts from something that works, with notes on why the last try didn't.
- **One unit of work per session.** "Implement F3 and nothing else." Small scope, fresh context, a clear exit.
- An **outer loop** in plain code: pick the next unfinished feature, start a session, check, record, repeat. The
  minimal version of this idea is a shell `while` loop feeding the same prompt to a coding agent forever (often
  called the "Ralph" loop); everything in this node is that loop plus checks.

In `loop` (self-report) the agent may mark any feature passing, not just the current one: one optimistic session
can "finish" the backlog. That's the self-report problem in its purest form, and the ablation shows it.

**Don't trust the agent's bookkeeping.** If the agent edits the progress file, it can also delete a feature it
couldn't do, reset an attempt counter, or mark something passing. Your `validate_update` (AGENT-OFF) is the
harness's rule: the agent may move a feature to `in_progress` and write notes; only the harness counts attempts and
decides `passing`/`failing`. An invalid edit is rolled back and logged. And **detect stalls**: if several sessions
add nothing, stop and call a human rather than burning money in a loop.

---

## §4 Verification you control

Who says a feature is done decides what "done" means:

| Who decides | Evidence | What it misses |
|---|---|---|
| The agent (self-report) | its own word | everything: this is the baseline's problem |
| The harness runs the agent's tests | green tests | weak tests: an agent can write tests that pass without checking the spec |
| A separate evaluator agent | review of spec vs diff, can run tests | what the evaluator misses; it costs extra calls |
| Hidden acceptance tests | your tests, outside the workspace | only what you thought to test |

**The evidence itself can be attacked.** Tests run by importing code from the workspace, so the workspace can change
how tests run: a file named `pytest.py` shadows pytest when Python is started in that directory, a `conftest.py` or
`sitecustomize.py` runs before any test. The harness runs tests in isolated mode (`python -I`) from outside the
workspace, and treats such files as tampering. And the local sandbox is not a boundary: code the agent writes can
import the course package and find the hidden tests' location. Run real experiments in a container (Node 03, E3),
and flag diffs that reach for the harness.

So the harness layers them: it runs the suite itself and requires the feature's test file to exist; a **separate
evaluator** (different prompt, read-only tools, told to be skeptical, must return a structured verdict, fails
closed) reviews each feature; and the **acceptance tests**, which the agent never sees, are the experiment's
ground truth. The key metric this produces is **overclaims**: features the harness believed were passing that the
hidden tests reject. It measures how much your harness's notion of "done" can be trusted.

Why a separate evaluator works better than asking the generator to check itself: tuning one agent to be skeptical
is easier than making the author critical of its own work, and the evaluator didn't spend 30 turns convincing
itself the code is right. Same lesson as Node 09's evaluator-optimizer, at a larger grain.

---

## §5 Hooks: rules that always run

A prompt says "never edit existing tests". A **hook** makes it so. Hooks are deterministic code the harness runs
at fixed points:
- **Before a tool call** (can block, with a reason the model reads): block shell commands that write to protected
  files. The permission gate covers the file tools; the shell is the side door.
- **After a tool call** (can add feedback): compile a Python file right after it's edited and report a syntax error
  immediately.
- **When the agent wants to stop** (can refuse): run the test suite; if it's red, send the agent back with the
  output. Cap the continuations so a hook can't loop forever.

Use a hook when a rule must hold every time and can be checked mechanically. Use the prompt for judgment. A hook
that the model can't satisfy (a flaky test, a check it can't see) turns into a loop: give it a cap and a clear
message.

Hooks overlap with the permission gate, and that's fine: in this harness the unattended gate already denies every
shell command that writes to a protected file (it answers "ask", and nobody is there to approve), so the pre-tool
hook adds nothing in the lab. It matters when the gate is looser (a human approving in a hurry, Claude Code's auto
mode): defense in depth means each layer must hold on its own.

---

## §6 Skills and project memory

Two ways to give the agent knowledge:
- **Always on**: `AGENTS.md` / `CLAUDE.md`. Short house rules every session needs (money is integer cents; never
  edit tests; how to run tests). Costs tokens on every call, so keep it short and current.
- **On demand**: **skills**, folders with a `SKILL.md` (name, description, instructions, maybe scripts). Only the
  name and one-line description sit in the prompt; the body is loaded when the agent decides it applies
  (progressive disclosure). The promo project ships one: how to test boundary cases.

The open question with skills is whether the agent loads them when it should. That's measurable: count
`load_skill` calls, and compare acceptance results with and without.

---

## §7 Measuring a harness

An **ablation**: the same backlog, the same model, fresh workspaces, adding one piece at a time:

| Config | Fresh sessions | Harness decides | Evaluator | Hooks + skills |
|---|---|---|---|---|
| `single` | | | | |
| `loop` | ✓ | | | |
| `loop+verify` | ✓ | ✓ | | |
| `loop+verify+eval` | ✓ | ✓ | ✓ | |
| `full` | ✓ | ✓ | ✓ | ✓ |

Fairness matters as much as in Node 10: every config gets the same turn budget per session (a stop hook's
continuations come out of it), and a run cut short by the budget is reported as "budget", not as a failure.

Report per configuration: features accepted by the hidden tests, overclaims, tampering, cost, turns, sessions and
wall time. Then run the best and the baseline across **several models**: a piece that's essential for a small model
may be pure overhead for a frontier one. One trial per cell is an anecdote (Node 04): look for large, consistent
differences, and repeat the cells you'll base a decision on.

---

## Design trade-offs

| Decision | Option A | Option B | Choose by |
|---|---|---|---|
| Session scope | whole backlog | one feature | backlog size vs context; recovery points |
| Who marks done | agent | harness checks + evaluator | how expensive an overclaim is |
| Failed attempt | keep partial work | reset to last good commit | whether half-done code helps the next session |
| Rule enforcement | prompt | hook | must it hold every time? can code check it? |
| Knowledge | always in the prompt | skill on demand | how often it's needed vs its size |
| Evaluator model | same as the worker | different/stronger | correlated blind spots vs cost |

## Common failure modes and debugging

| Symptom | Likely cause | Fix |
|---|---|---|
| Every feature "passing", hidden tests fail | self-report or agent-written tests trusted | harness verification + evaluator + acceptance |
| The loop runs forever | no stall detection; a check the agent can't pass | `stalled()`; cap attempts per feature |
| Agent deleted a feature from the progress file | progress edits not validated | `validate_update`, roll back |
| Stop hook ping-pong | hook can't be satisfied | cap continuations; make the message actionable |
| Skill never loaded | description doesn't match how the task is phrased | rewrite the description; measure loads |
| `full` costs 3× and accepts the same as `loop+verify` | the evaluator adds nothing for this model | drop it for this model; keep the measurement |

## Self-check
1. Why does a fresh session per feature help even when the model's context window could hold the whole backlog?
2. The agent marked F3 `passing` in `features.json`. Under `loop+verify`, what happens to that edit, and why?
3. `loop+verify` reports 5/5 passing; acceptance says 1/5. What did the harness believe, and which piece fixes it?
4. Why reset to the last good commit after a failed attempt instead of letting the next session continue?
5. Give one rule that belongs in a hook and one that belongs in a prompt.
6. When would you remove the evaluator from your harness?

<details><summary>Answers</summary>

1. Long contexts degrade attention and accumulate stale tool output (Node 06); a fresh session reads only what's
   current (spec, code, progress), and each session has a small, checkable goal and a recovery point.
2. `validate_update(..., allow_passing=False)` rejects it, the harness restores its own version, and the harness
   decides the status from its own checks.
3. It believed the agent's own tests, which passed without checking the spec (placeholder or shallow tests). An
   evaluator that reads the spec against the diff, and better acceptance-style checks, close the gap; the
   overclaims metric shows how big it is.
4. A half-done change can break earlier features and confuse the next session; starting from the last state that
   passed, plus notes on what failed, is a known-good base.
5. Hook: "never write to existing test files" (mechanical, must always hold). Prompt: "prefer the smallest change
   that satisfies the spec" (judgment).
6. When the ablation shows it doesn't change acceptance for this model (it only adds cost and time), e.g. after a
   model upgrade; re-run the ablation when models change.
</details>

## Socratic review prompt
> Here's my harness ablation table and ADR 0009 draft: [paste]. Act as the engineering manager who has to pay for
> these runs. Ask me one question at a time: which numbers justify each harness piece, whether one trial per cell is
> enough to drop a piece, how I'd detect a harness piece going stale after a model upgrade, and what my overclaim
> rate means for how much review a human still has to do.
