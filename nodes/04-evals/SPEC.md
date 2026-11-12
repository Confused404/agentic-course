# SPEC: Node 04: an eval harness (tasks, graders, judge, simulated users, runner, reports, flywheel, CLI)

**For the coding agent.** Read `AGENTS.md`. Background: TEXTBOOK §2–§10.
**AGENT-OFF:** `agentlab/evals/stats.py` (the learner's). Your `report.py` imports and calls it; its tests stay red
until the learner writes it. Don't modify the task files in `nodes/04-evals/evals/` (they're the course's suite).
Keep `agentlab/evals/mini.py` (Node 02) working; the new harness lives beside it.

## Files
```
create  agentlab/evals/task.py
create  agentlab/evals/graders.py
create  agentlab/evals/judge.py
create  agentlab/evals/user_sim.py
create  agentlab/evals/runner.py
create  agentlab/evals/report.py
create  agentlab/evals/flywheel.py
create  agentlab/evals/__main__.py
modify  agentlab/assistant/support.py     (one span per chat turn, see 8)
```

## 1. `task.py`
```python
@dataclass
class Task:
    id: str
    customer_id: int
    graders: list[dict]
    turns: list[str] = field(default_factory=list)      # scripted user messages, OR:
    user_sim: dict | None = None                        # {"persona", "goal", "facts", "max_turns"} (exactly one of the two)
    tags: list[str] = field(default_factory=list)
    split: str = "dev"                                  # "dev" | "heldout"
    kind: str = "regression"                            # "regression" | "capability"
    note: str = ""
    golden: list[dict] | None = None                    # scripted agent steps a CORRECT agent would take (Tier 1)
    bad: list[dict] | None = None                       # scripted steps of a WRONG agent; graders must fail it
    golden_user: list[str] | None = None                # scripted simulated-user messages for Tier 1 (ends with "[DONE]")
    bad_caught_by: list[str] | None = None              # grader types that must be among those failing the bad script

def load_tasks(path: str | Path, split: str | None = None, tags: list[str] | None = None) -> list[Task]
    # path: a YAML file (list of tasks) or a directory of *.yaml files (sorted). Filter by split and by "has any of tags".
    # Validate: unique ids, exactly one of turns/user_sim, at least one grader (a task with no graders always passes),
    # every grader has a known "type" -> ValueError naming the task.
def script_from_steps(steps: list[dict]) -> list
    # {"say": str} -> fake.say;  {"call": name, "args": {...}} -> fake.call(name, **args);
    # {"calls": [[name, {args}], ...]} -> fake.calls(...)
```

## 2. `graders.py`
```python
@dataclass
class GradeResult:
    grader: str                  # the grader's "type" (plus a suffix if the task has two of the same type: "refund#2")
    verdict: str                 # "pass" | "fail" | "unknown"
    detail: str = ""

@dataclass
class TrialContext:
    conn: sqlite3.Connection
    before: dict                 # snapshot(conn) taken before the trial
    messages: list[Message]      # the whole conversation (assistant.messages at the end)
    replies: list[str]           # every assistant reply, in order
    customer_id: int

    @property
    def tool_calls(self) -> list[ToolUseBlock]       # every ToolUseBlock in messages, in order
    @property
    def final_reply(self) -> str                     # replies[-1] or ""

def snapshot(conn) -> dict
    # {"refund_ids": set, "ticket_ids": set, "email_ids": set, "max_audit_id": int,
    #  "order_status": {order_id: normalized status}}
def grade(spec: dict, ctx: TrialContext, judge=None, budget: Budget | None = None) -> GradeResult
```
All reply graders **normalise text first** (NFKC, curly quotes → straight, collapsed whitespace, lowercase), so
"aren’t" matches "aren't".
Grader types (spec keys besides "type"). Only rows created **during** the trial count (compare with `ctx.before`):
| type | keys | pass when |
|---|---|---|
| `refund` | `order_id`, `status` (`issued`/`pending_approval`/`none`), optional `amount_cents`, optional `reason` | for `none`: no new refund for the order. Otherwise a new refund for the order with that status (and amount/reason if given) |
| `refund_reasons_only` | `reasons` | every new refund's reason is in the list |
| `escalated` | `expected` (bool) | a new ticket with status `escalated` exists == expected |
| `order_status` | `order_id`, `status` | current normalized status equals |
| `no_side_effects` | – | no new audit_log rows at all |
| `tools_called` | `tools` | each was called at least once |
| `tools_called_any` | `tools` | at least one of them was called |
| `tools_not_called` | `tools` | none was called |
| `tool_order` | `before`, `after` | if `after` was called, `before` was called earlier (pass if `after` never called) |
| `max_tool_calls` | `n` | total tool calls ≤ n |
| `reply_contains_any` | `values`, optional `scope` (`final` default / `any`) | some value occurs (case-insensitive) in the final reply / in any reply |
| `reply_not_contains` | `values` | no value occurs in **any** reply (case-insensitive) |
| `reply_regex` | `pattern`, optional `scope` | `re.search(pattern, text, re.I)` |
| `reply_not_regex` | `pattern` | the pattern matches **no** reply (e.g. a false "I've refunded" claim) |
| `judge` | `rubric` | delegates to `judge(model, rubric, ctx, budget)` (see 3); if `judge` is None → `unknown` with detail "no judge configured" |
`detail` explains failures concretely (e.g. `"new refunds for 4822: []"`). Unknown type → ValueError.

## 3. `judge.py`
```python
JUDGE_SYSTEM: str
JUDGE_SCHEMA = {"type": "object", "additionalProperties": False,
                "properties": {"reasoning": {"type": "string"}, "verdict": {"type": "string", "enum": ["pass", "fail", "unknown"]}},
                "required": ["reasoning", "verdict"]}           # reasoning FIRST (TEXTBOOK §3 rule 4)
def render_evidence(ctx: TrialContext, max_chars: int = 12_000) -> str
def judge(model: ChatModel, rubric: str, ctx: TrialContext, budget: Budget | None = None) -> GradeResult
```
`render_evidence`: the conversation as plain text, one entry per block: `CUSTOMER: …`, `ASSISTANT: …`,
`TOOL CALL name(args-json)`, `TOOL RESULT (error) …` (each tool result cut to 600 chars). If the total exceeds
`max_chars`, keep the first 30% and the last 70% with a `[... omitted ...]` marker.
`JUDGE_SYSTEM` says: you are grading a customer-support transcript against ONE rubric; the tool results are ground
truth; judge only the rubric, not style; answer "unknown" if the evidence is insufficient or the rubric doesn't apply;
reasoning first, then verdict.
`judge`: one `model.complete(system=JUDGE_SYSTEM, messages=[user: "RUBRIC: …\n\nTRANSCRIPT:\n…"], max_tokens=1500,
json_schema=JUDGE_SCHEMA, effort="low")`; charge `budget` if given; parse the JSON text. Unparseable output, a
missing verdict or a model exception → `unknown` with the reason in `detail`, **except `BudgetExceeded`, which must
propagate** (it's a `RuntimeError`, so catch it explicitly first). `grader="judge"`, `detail` = reasoning.

## 4. `user_sim.py`
```python
SIM_SYSTEM: str      # template with {persona}, {goal}, {facts}
class SimulatedUser:
    def __init__(self, model: ChatModel, persona: str, goal: str, facts: str = "", max_turns: int = 6,
                 budget: Budget | None = None)
    def first_message(self) -> str
    def reply(self, assistant_text: str) -> str | None        # None = conversation over
```
The simulator keeps its own history with **roles flipped** (the assistant's replies are its "user" messages). SIM_SYSTEM
tells it: you are a customer; write only the customer's next message, 1–3 sentences; reveal facts only when asked or
when relevant; never invent order numbers or facts beyond the ones given; when the goal is achieved or clearly refused,
reply exactly `[DONE]`. `first_message` asks it to open the conversation. `reply` returns None if the model says
`[DONE]` (anywhere in its text, after strip) or after `max_turns` user messages. `effort="low"`, `max_tokens=400`.
Keep `spent_usd` (sum of its own budget charges) so the runner can separate simulator cost from agent cost.

## 5. `runner.py`
```python
@dataclass
class Trial:
    task_id: str
    trial: int
    model: str               # the label from model_factories
    verdict: str             # "pass" | "fail" | "unknown" | "error"
    grades: list[GradeResult]
    replies: list[str]
    tool_calls: list[str]    # tool names, in order
    transcript: list[dict]   # Message.to_dict() for each message
    cost_usd: float
    latency_s: float
    turns: int               # model calls made by the agent
    stops: list[str]         # LoopResult.stop for each chat() call
    error: str | None
    tags: list[str]
    split: str
    error_kind: str | None = None   # "provider" (rate limit, timeout, 5xx: infrastructure) | "agent" | "timeout"
    overhead_usd: float = 0.0       # judge + simulator spend; cost_usd is the AGENT's spend only

def error_kind(e: BaseException) -> str   # "provider" if the exception's module is anthropic/openai/httpx/httpcore or its
                                          # class name contains RateLimit/Timeout/Connection/Overloaded/InternalServer/
                                          # ServiceUnavailable; else "agent"
def run_trial(task: Task, model: ChatModel, *, template_db: Path, trial: int = 0, model_label: str | None = None,
              budget: Budget | None = None, judge_factory=None, sim_factory=None, assistant_opts: dict | None = None,
              ceiling_s: float = 600.0) -> Trial
def run_eval(tasks: list[Task], model_factories: dict[str, Callable[[], ChatModel]], *, template_db: Path,
             trials: int = 3, budget: Budget | None = None, judge_factory=None, sim_factory=None,
             assistant_opts: dict | None = None, out_dir: Path | None = None, meta_extra: dict | None = None,
             retry_provider_errors: bool = False) -> list[Trial]
```
Provider errors and timeouts are infrastructure noise (TEXTBOOK §2): they're recorded, but the report excludes them
from graded trials, like `unknown`. `ceiling_s` is a generous wall-clock kill ceiling: if the conversation runs past
it, stop and record `error_kind="timeout"`. Delete the trial's temp directory when done.
`run_trial`: fresh DB (`db.snapshot(template_db, <tmpdir>/shop.db)`), `before = snapshot(conn)`, build
`SupportAssistant(model, conn, task.customer_id, budget=budget, **(assistant_opts or {}))`. Conversation:
- scripted: send each of `task.turns` in order;
- simulated: `sim = SimulatedUser(sim_factory(), **task.user_sim)`; message = `sim.first_message()`; loop: reply =
  `assistant.chat(message)`; next = `sim.reply(reply)`; stop when None. Hard cap of 12 assistant turns.
Then grade every spec (judge graders get `judge_factory()` as the model, or None if no factory, and the budget). Verdict: `error` if an
exception escaped the agent (record `f"{type}: {msg}"`; `BudgetExceeded` must propagate instead, the run is over.
Note your loop turns a budget hit into `stop == "budget"` rather than raising, so if any chat() stopped with
`"budget"`, raise `BudgetExceeded` yourself);
else `fail` if any grade failed; else `unknown` if any unknown; else `pass`. Cost = budget spend during the trial
(0.0 without budget). Latency = wall-clock for the conversation. Always close the connection.
`run_eval`: for trial in range(trials), for task, for each model label (this interleaving spreads each model's trials
over time, TEXTBOOK §2): `model_factories[label]()` fresh per trial. With `retry_provider_errors`, a trial whose
`error_kind` is provider/timeout is re-run once after a short pause. If `out_dir` is given: create it, write
`meta.json` at the start (`started`, `models`, `trials`, `task_ids`, `tasks_sha256` of the task definitions, a hash of
each `assistant_opts` value, plus everything in `meta_extra`: the CLI adds prompt name, split, suite path, git sha,
resolved `provider:model` ids, judge and sim) and append one JSON line per trial to `trials.jsonl` as it completes (a
crash keeps finished trials). Print one progress line per trial.
`load_trials(path) -> list[Trial]` reads a `trials.jsonl` back (GradeResults restored).

## 6. `report.py` (uses the learner's `stats.py`)
```python
def per_task(trials: list[Trial]) -> dict[str, dict[str, tuple[int, int]]]   # {model: {task_id: (passes, graded_trials)}}
    # graded_trials excludes "unknown"; "error" counts as a graded failure
def summarize(trials: list[Trial], k: int = 3) -> dict[str, dict]
def compare(trials: list[Trial], model_a: str, model_b: str) -> dict          # {"tasks", "diff", "lo", "hi"} via paired_diff_ci on per-task rates
def pareto(summary: dict) -> list[str]                                       # models not dominated on (task_mean ↑, cost_per_trial ↓)
def render_markdown(trials: list[Trial], title: str = "Eval report", k: int = 3) -> str
```
"Graded" trials exclude `unknown` and errors whose `error_kind` is provider/timeout; agent errors count as failures.
`summarize` per model: `trials`, `tasks`, `passes`, `unknown`, `errors`, `provider_errors`, `pass_rate` (passes /
graded), `wilson` = `wilson_interval(passes, graded)`, `pass_rate_conservative` (passes / all trials: unknowns and
errors count as failures), `task_mean` / `task_ci` = `bootstrap_mean_ci` over per-task rates, `pass_at_k` = mean over
tasks with ≥ k graded trials of `pass_at_k(n, c, k)`, `pass_hat_k` / `pass_hat_k_ci` = `bootstrap_mean_ci` over those
tasks' `pass_hat_k(n, c, k)` values (None if none qualify), `cost_per_trial`, `cost_per_pass` (None if 0 passes),
`overhead_usd`, `latency_p50`, `latency_p90` (nearest-rank, ignoring None), `by_tag` = `{tag: rate}` and
`by_tag_counts` = `{tag: (passes, graded)}`.
`compare` raises ValueError naming the available models if either model is missing.
`render_markdown`: the **headline is the task mean with its bootstrap CI** (the pooled Wilson interval is shown as
"per-trial", labelled as ignoring that trials of a task are correlated), then pass^k with CI, pass@k, conservative
rate, unknown, errors (provider), $/trial, $/pass, p50 latency; the Pareto set and judge+simulator spend; a per-task
table (cells `c/n`); a by-tag table with `c/n` cells, labelled exploratory; and "Failures to read": one failed / unknown
/ error trial per (task, model), up to 15, with the failing graders' details. Percentages with 0 decimals.

## 7. `flywheel.py`
```python
def mine_traces(trace_dir: Path, min_turns: int = 6) -> list[dict]
def candidates_to_yaml(cands: list[dict]) -> str
```
Read every `*.jsonl` trace file. For each root span named `invoke_agent support-chat` (see 8), collect its descendant
spans. Flag it with reasons: `"tool_error"` (any `execute_tool` span with `course.tool.is_error` true), `"escalated"`
(an `execute_tool escalate_to_human` span), `"long"` (≥ min_turns `chat` spans), `"error"` (`course.stop == "error"`),
`"stopped"` (any other `course.stop` not equal to `end_turn`). Return flagged ones as
`{"trace_id", "customer_id", "user_message", "turns", "reasons", "tools": [names]}` where `turns` is every user message
of the same `course.session_id` up to and including this `course.turn_index` (a flagged "Yes, please do." is useless
without the turn before it). `candidates_to_yaml` emits task stubs (`id: cand_<trace_id[:8]>`, `customer_id`,
`turns`, `graders: []`, `note: "from trace …; reasons: …; TODO graders"`). They're deliberately invalid
(`load_tasks` rejects empty graders) until a human labels them.

## 8. `support.py` change
Give `SupportAssistant` a `session_id` (uuid4 hex) and a `turn_index` (incremented per `chat`). Wrap the body of
`chat` in `tracing.agent_span("support-chat", customer_id=..., user_message=user_text, session_id=..., turn_index=...)`.
Set `course.stop` to `"error"` first, then to `result.stop` after the loop returns (so an exception leaves `"error"`).
(The loop's own `invoke_agent support` span becomes its child.)

## 9. `__main__.py`: `python -m agentlab.evals ...`
```
run --suite PATH [--split dev|heldout|all] [--tags a,b] --models fast,gpt-fast [--trials 3] [--budget 2.0]
    [--judge ALIAS] [--sim ALIAS] [--prompt v1|...] [--out runs/evals/<timestamp>] [--retry-errors]
report RUN_DIR [--k 3]            # writes RUN_DIR/report.md and prints it
compare RUN_DIR --a MODEL --b MODEL     (or two run dirs: compare RUN_A RUN_B --model M, comparing the SAME model
                                         across runs; --model is required in that form, and only that model's trials are used)
mine [--trace-dir runs/traces] [--out candidates.yaml]
```
Defaults: judge and sim aliases from `config/models.toml [evals]`; split `dev`; one shared `Budget(--budget)`.
`--prompt` selects a system prompt by name from `agentlab.assistant.prompts` (`v1` → `SYSTEM_PROMPT_V1`; Node 05 adds
more) and passes it as `assistant_opts={"system_prompt": ...}`.

## Done when
`make grade N=04` passes except the expected-red tests that need `stats.py`: all of `test_stats.py`, plus
`test_runner_report.py::test_summary_numbers`, `::test_compare_pareto_and_markdown` and
`::test_provider_errors_are_not_model_failures`. In particular **`test_suite_tier1.py` must be green**: every task's golden script passes and every bad
script fails. If a task looks wrong to you, say so; don't edit the suite. Explain your diff.
