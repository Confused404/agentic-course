# SPEC: Node 12: a harness for multi-session feature work, and its ablation

**For the coding agent.** Read `AGENTS.md`. Background: TEXTBOOK §2–§7.
**AGENT-OFF (the learner's; never write or edit it):** `agentlab/harness/progress.py` (`next_feature`,
`validate_update`, `record_attempt`, `stalled`). Call them through the module (`progress_module.next_feature`, ...)
so tests can substitute them.
**GIVEN (don't rewrite):** `progress.py`'s `Feature`, `STATUSES`, `MAX_NOTES`, `load`, `save`;
`agentlab/harness/project.py` (`new_workspace`, `checkpoint`, `head`, `reset_to`, `diff_since`, `changed_files`,
`run_visible_tests`, `run_acceptance`, `read_features`, `FEATURES`); everything under `nodes/12-harness/`
(project template, acceptance tests). Reuse Node 03's `make_dev_tools`, `GatedExecutor`, `PermissionGate`,
`LocalSandbox` unchanged.

## Files
```
create  agentlab/harness/hooks.py       (1)
create  agentlab/harness/session.py     (2)
create  agentlab/harness/evaluator.py   (3)
create  agentlab/harness/loops.py       (4)
create  agentlab/harness/evals.py       (5)
create  agentlab/harness/__main__.py    (6)
```
Nothing outside `agentlab/harness/` changes. `make grade-upto N=12` must stay green for 00–11.

## 1. `hooks.py`
```python
PreHook = Callable[[str, dict], str | None]                 # (tool, args) -> deny reason or None
PostHook = Callable[[str, dict, ToolResultBlock], str | None]   # -> feedback to append, or None
@dataclass
class HookedExecutor:        # ToolExecutor wrapper: inner, pre=[], post=[], events=[]
    # execute: each pre hook in order; the first reason -> error result "Blocked by a project hook: <reason>" and an
    # event "pre-hook denied <tool>: <reason>", inner not called. Else inner.execute; post-hook notes are appended
    # to the result text as "\n\n[hook] <note>" lines (is_error unchanged) and an event "post-hook on <tool>: …"
def protect_in_shell(protected: list[str]) -> PreHook   # run_shell only: deny when the command mentions a protected
    # path AND writes: >, >>, sed -i, rm, mv, cp, tee, truncate, git checkout|restore|rm; message contains "protected"
def syntax_check(workspace) -> PostHook                 # after a successful write_file/edit_file of a .py file:
    # `python -m py_compile` it (sys.executable); on failure return a note containing "compile"
```

## 2. `session.py`
```python
HARNESS_SYSTEM: str      # feature work in the promo project: read AGENTS.md and the spec, small steps, tests for
                         # every rule, run the suite, short report; denied calls: don't work around them
PROTECTED = ["features.json", "BACKLOG.md", "AGENTS.md", "conftest.py", "skills/*"]
class ProjectGate(PermissionGate):    # __init__(workspace, initial_tests: set[str], progress_writable=False)
    # write tools: features.json -> allow if progress_writable; PROTECTED -> deny; tests/test_*.py -> deny if in
    #   initial_tests ("existing test"), else allow (writing NEW tests is the job); otherwise defer to Node 03's gate
    # run_shell: if Node 03's gate says "ask" and the command is exactly `python|python3|.venv/bin/python -m
    #   promo|py_compile <args>`, allow; otherwise Node 03's decision
@dataclass(frozen=True) class Skill: name; description; body
def load_skills(root) -> list[Skill]     # <root>/*/SKILL.md, front matter "---\nname: …\ndescription: …\n---\n"
def skills_index(skills) -> str          # one line per skill: "- <name>: <description>"
def skill_tool(skills, events=None) -> Tool   # load_skill(name) -> body, appending "skill loaded: <name>" to events;
                                              # unknown -> ToolError listing the names
@dataclass class SessionResult: loop: LoopResult; events=[]; continuations=0; cost_usd=0.0; turns=0
def run_session(model, workspace, task, *, hooks=False, skills=False, stop_hook=False, progress_writable=False,
                budget=None, max_turns=30, max_continuations=2, protected_tests=None) -> SessionResult
```
`run_session`: protected tests = `protected_tests` if given (the harness passes the tests present when the RUN started,
so tests written by earlier sessions stay editable), else `tests/test_*.py` present now; ProjectGate matches paths
case-insensitively; tools = `make_dev_tools(ws,
LocalSandbox(ws, venv=Path(sys.prefix)))` behind `GatedExecutor(…, ProjectGate(…), approver=always False)`
(unattended: "ask" means no); if `hooks`, wrap in `HookedExecutor(pre=[protect_in_shell(initial tests +
["features.json"])], post=[syntax_check(ws)])`; system = HARNESS_SYSTEM + AGENTS.md; if `skills` and skills exist,
add the `load_skill` tool and the index to the system prompt. Run the Node 02 loop (`max_tokens=8000`). **Stop hook**:
while `stop_hook` and the loop stopped with "end_turn" and continuations < max and turns used < max_turns: run
`project.run_visible_tests`; if green, stop; else continue the SAME transcript with a user message starting
"[stop hook]" that includes the test output tail, and an event containing "stop hook"; each continuation gets only
the REMAINING turns (`max_turns - turns used`), so a hooked session never gets more turns than an unhooked one.
Cost and turns sum over continuations. Events also include the
gate's denials ("gate denied …") and the hook events.

## 3. `evaluator.py`
```python
EVALUATOR_SYSTEM: str    # skeptical QA reviewing ONE feature: check every rule, run the tests, look for untested
                         # rules and weakened tests; call verdict once; passed only if you'd ship it
def feature_spec(ws, feature_id) -> str      # the "## F3: …" section of BACKLOG.md up to the next "## "; KeyError
@dataclass class Verdict: passed: bool; issues: list[str] = []; cost_usd = 0.0; turns = 0; out_of_budget = False
def evaluate(model, ws, feature_id, diff, *, budget=None, max_turns=15) -> Verdict
    # tools: read_file, list_dir, grep (from make_dev_tools), run_tests (harness-run suite: "PASSED"/"FAILED" + tail),
    # verdict(passed: bool, issues: [str]) once (second call ToolError). User message: the spec + the diff (last
    # 12,000 chars). No verdict -> Verdict(False, ["evaluator gave no verdict (stop=…)"], out_of_budget=(loop stop
    # was "budget")); passed only if the
    # verdict's passed is the boolean true. NO write tools.
```

## 4. `loops.py`
```python
@dataclass(frozen=True)
class HarnessConfig: name; loop=False; verify=False; evaluator=False; hooks=False; skills=False
CONFIGS = {"single", "loop" (loop), "loop+verify" (loop, verify), "loop+verify+eval" (loop, verify, evaluator),
           "full" (all five)}
SINGLE_TASK, LOOP_TASK, FINISH_SELF, FINISH_VERIFIED: str     # LOOP_TASK contains "feature {fid}" and
                                                             # "tests/test_{fid_lower}.py"; see TEXTBOOK §3
@dataclass class HarnessResult: config; stop=""; sessions=0; features=[] (final features.json dicts);
    passing_counts=[]; events=[]; tamper=[]; evaluator_rejections=0; continuations=0; cost_usd=0.0; turns=0;
    latency_s=0.0; to_dict()
def run_harness(config, model_factory, ws, *, budget=None, max_sessions=8, session_turns=30, max_attempts=2)
    -> HarnessResult      # model_factory(role) with role "worker" | "evaluator"
```
- Every session: `run_session(model_factory("worker"), ws, task, hooks=config.hooks, skills=config.skills,
  stop_hook=config.hooks, progress_writable=True, budget=budget, max_turns=…, protected_tests=<tests at the start of
  the run>)`.
- **Budget**: if the budget is spent after a session, or the evaluator's Verdict has out_of_budget, stop with "budget"
  WITHOUT resetting or recording an attempt (a session cut off by money says nothing about the feature).
- **Progress check after every session**: load features.json and `progress_module.validate_update(before, after,
  allow_passing=…)`; a load error (incl. OSError) or any problem -> events "progress edit rejected: <problem>" and save
  `before` back (the harness's version). The validated `after` is what the attempt is recorded on, so the agent's
  notes survive: with verify, notes = the harness's reason (if failing) then "agent: <agent's note>".
- `single`: one session with SINGLE_TASK and `max_turns = session_turns * 4`, allow_passing=True; checkpoint;
  stop "single".
- `loop`: repeat: `nxt = next_feature(feats, max_attempts)`; None -> stop "done"; sessions ≥ max_sessions ->
  "max_sessions"; budget spent ≥ limit -> "budget". Remember `base = head(ws)`. Session with LOOP_TASK (FINISH_SELF
  or FINISH_VERIFIED; the feature's notes if any).
  - without `verify`: allow_passing=True; the feature counts as passing iff the agent set it "passing"
    (`record_attempt(after, id, claimed, notes)`).
  - with `verify`: allow_passing=False; ok = `run_visible_tests` green AND `tests/test_<id lower>.py` changed since
    `base` (else note "no tests/test_<id>.py written or changed in this session"); if ok and `evaluator`:
    `evaluate(model_factory("evaluator"), ws, id, diff_since(ws, base))`, add its cost/turns, a FAIL counts in
    evaluator_rejections, event "evaluator on <id>: PASS|FAIL", notes "evaluator: <issues>". Not ok ->
    `reset_to(ws, base)`. Then `record_attempt(after, id, ok, notes)` (notes for failures start with "harness check
    failed" or "evaluator").
  - save features.json, `checkpoint(ws, "<id>: session <n>")`, append the passing count; `stalled(...)` -> "stalled".
- At the end: `features` = the final features.json; `tamper` (sorted) = files changed since the start that are
  initial tests or match PROTECTED (features.json excepted; case-insensitive), plus `project.suspicious_files`
  (a fake pytest.py, sitecustomize.py, any conftest.py, .pth files, .py files outside promo/ and tests/), plus the
  entry "(diff references the harness: agentlab / 12-harness)" when an added line mentions either.

## 5. `evals.py`
```python
def to_trial(label, r: HarnessResult, acceptance: dict, visible_ok: bool, k=0) -> Trial   # keyword args;
    # task_id "promo-backlog"; model=label; verdict "pass" iff every feature accepted AND no tamper; grades: one per
    # feature; extra={accepted, of, claimed (ids marked passing), overclaims (claimed − accepted, sorted),
    # visible_green, sessions, tamper, evaluator_rejections, continuations, stop, denials (gate + hook),
    # skill_loads ("skill loaded" events)}
def run_ablation(configs, models, get_model, out_dir, *, evaluator_model=None, trials=1, budget=None,
                 max_sessions=8, session_turns=30) -> list[Trial]
    # trial -> model -> config; label "<config>@<alias>"; a fresh workspace out_dir/"ws-<config>-<alias>-<k>"
    # ("+" -> "_"); evaluator role uses evaluator_model if given; BudgetExceeded propagates; other exceptions ->
    # error trial (error_kind from the real exception); after each run: run_acceptance, run_visible_tests, write <ws>/.harness-result.json, append the
    # trial to trials.jsonl (truncated at start); budget over its limit -> BudgetExceeded
def summarize(trials) -> {label: {n, accepted (mean), of, all_accepted, overclaims (mean count), visible_green,
                                  tamper, cost, turns, sessions, minutes, rejections, continuations, skill_loads,
                                  stops {stop: count}, per_feature}}
def render(trials) -> str     # one table row per label, formatted "| <label> | 5.0/5 | 1/1 | …", then per-feature
                              # lines "- <label>: F1 1/1, …", then a line defining overclaims
```

## 6. CLI: `python -m agentlab.harness`
```
new DEST            a fresh workspace (for coding-agent runs, YOU_DO 6)
accept WORKSPACE    hidden acceptance tests per feature + "<n>/5 features accepted" (free); not a workspace
                    (no promo/) -> "error: …" on stderr, exit 2
run --configs single,loop,loop+verify,loop+verify+eval,full --models fast [--evaluator-model A] [--trials 1] [--budget 2]
    [--max-sessions 8] [--session-turns 30]
report RUN_DIR [RUN_DIR ...]
show WORKSPACE      the run's result file (if any), features.json, git log, last commit's diffstat
```
`run` validates configs (ValueError) and resolves every alias (`config.resolve`) before creating anything; output in
`new_run_dir(RUNS / "harness")` (module-level `from agentlab.config import RUNS, new_run_dir`); on
`BudgetExceeded` reports the completed runs.

## Done when
`make grade N=12` passes except `test_progress.py` (the learner's). Explain your diff: where state lives between
sessions, who decides "passing" in each config, and what the stop hook does when tests fail.
