# SPEC: Node 06: context strategies, long-term memory, multi-session evals

**For the coding agent.** Read `AGENTS.md`. Background: TEXTBOOK §2–§8.
**AGENT-OFF (the learner's; never write or edit them):**
- `agentlab/context/split.py::split_for_compaction` (your strategies call it);
- `agentlab/context/prompts.py::COMPACTION_PROMPT` (your `Compaction` strategy uses it as the summariser's system prompt);
- `agentlab/memory/policy.py::memory_policy` (your write path calls it).
Their tests (`test_split.py`, `test_compaction_prompt.py`, `test_memory_policy.py`) and every test that runs through
them stay red until the learner writes them. If you need one of them to test your own code, use a stub inside your
test, never in those files.
**GIVEN (don't rewrite):** `agentlab/context/longconv.py`, the `gen` subcommand in `agentlab/context/__main__.py`,
`Candidate`/`PolicyDecision`/pattern lists in `policy.py`, the suites in `nodes/06-context-memory/evals/`.

## Files
```
create  agentlab/context/tokens.py            (1)
create  agentlab/context/strategies.py        (2)
create  agentlab/memory/store.py              (3)
create  agentlab/memory/extract.py            (4)
create  agentlab/memory/tools.py              (4)
modify  agentlab/tools/base.py                ToolRegistry.with_tools (5)
modify  agentlab/assistant/support.py         context, memory, notes, transcript, turn_stats, end_session (5)
modify  agentlab/evals/task.py                sessions; memory grader types (6)
modify  agentlab/evals/graders.py             memory_contains / memory_absent; reply scopes (6)
modify  agentlab/evals/runner.py              sessions, transcript, Trial.extra, ceiling scaling (6)
modify  agentlab/evals/experiment.py          Variant.context / memory / notes (7)
modify  agentlab/evals/__main__.py            run --context/--memory/--notes; experiment keys (7)
create  agentlab/context/report.py            (8)
modify  agentlab/context/__main__.py          report, breakdown subcommands (8)
```
Every default must leave Nodes 02–05 behaving exactly as before: `make grade-upto N=06` must stay green for 00–05.

## 1. `agentlab/context/tokens.py`
```python
CHARS_PER_TOKEN = 4.0
def estimate_tokens(obj) -> int     # str: ceil(len/4); Message: its to_dict() as JSON; ToolSpec: asdict as JSON;
                                    # list/tuple: sum; None: 0; other: JSON (default=str)
def estimate_request(system: str, tools: list[ToolSpec], messages: list[Message]) -> int
def breakdown(system, tools, messages) -> dict[str, int]
    # keys: system, tools, customer_text, assistant_text, thinking, tool_calls, tool_results, total (= sum of others)
```

## 2. `agentlab/context/strategies.py`
```python
@dataclass
class PrepareStats:
    strategy: str
    action: str           # "none" | "dropped" | "cleared" | "compacted" | "failed"
    before_tokens: int    # estimate_request before
    after_tokens: int     # and after
    detail: str = ""

class ContextStrategy(Protocol):
    name: str
    history: list[PrepareStats]      # one entry appended per prepare() call
    def prepare(self, messages: list[Message], *, system: str, tools: list[ToolSpec]) -> list[Message]: ...
```
**Hysteresis** (all triggered strategies): `_should_act(n, trigger, last_after, min_growth)` is true when the trigger
is `None` (naive window), or when `n > trigger` and either the strategy hasn't acted yet or `n - last_after >=
min_growth` (default `trigger // 4`), where `last_after` is the estimate right after its last action. Each triggered
strategy takes `min_growth: int | None = None`. When an action leaves the estimate above the trigger, say so in
`detail` (`"still above trigger"`).
Rules for every strategy: never mutate the input messages or their blocks (copy-on-write: build new `Message`s and use
`dataclasses.replace` on blocks); never return a history with an orphaned tool result; append exactly one
`PrepareStats` per call.
| Class | Constructor | Behaviour |
|---|---|---|
| `Full` | `()` | returns `list(messages)`; action `none` |
| `SlidingWindow` | `(keep_turns=6, trigger_tokens=None, min_growth=None)` | if it shouldn't act (hysteresis): unchanged. Otherwise `old, kept = split_for_compaction(messages, keep_turns)`; return `kept` (`dropped` if `old` else `none`) |
| `ClearToolResults` | `(trigger_tokens=8000, keep_recent=3, keep_tools=DEFAULT_KEEP_TOOLS, min_growth=None)` | when it should act: replace the content of every tool result except the last `keep_recent` and those whose tool is in `keep_tools` with a stub that starts `[result cleared` and names the call (`name(json args)`) and says to call it again if needed. Results already starting with `[result cleared` are skipped. `DEFAULT_KEEP_TOOLS = ("issue_refund", "cancel_order", "escalate_to_human", "forget_memory", "update_case_notes")` |
| `Compaction` | `(summarizer, prompt, trigger_tokens=8000, keep_turns=4, budget=None, max_summary_tokens=1500, max_failures=3, min_growth=None)` | see below |

`Compaction.prepare`: if it shouldn't act (hysteresis), or `failures >= max_failures`: unchanged (`none`).
`failures` counts CONSECUTIVE failures (a success resets it to 0). Else
`old, kept = split_for_compaction(messages, keep_turns)`; if `old` is empty: unchanged. Else `budget.check()` (if a
budget), call `summarizer.complete(system=prompt, messages=[Message.user(render_for_summary(old))], tools=None,
max_tokens=max_summary_tokens)`, `budget.charge(summarizer.model, resp.usage, provider=summarizer.provider)`. If the
call raises (other than `BudgetExceeded`, which propagates and is not a failure), or the text is empty, or
`stop_reason` is not `end_turn` (a `max_tokens` stop is a truncated summary: also a failure): `failures += 1`,
action `failed`, return unchanged. Otherwise return
`[Message(kept[0].role, [TextBlock(<summary block>), *kept[0].content]), *kept[1:]]`, where the summary block is
`<conversation_summary>\n[a line saying it was written by the support system, not the customer]\n{summary}\n
</conversation_summary>\n\n`, with any `<conversation_summary>`/`</conversation_summary>` inside the summary text
escaped (so it can't close the tag); append the summary text to `self.summaries`.
Earlier summaries are inside `old`, so they are summarised again (recursive): no special case.

`render_for_summary(messages, max_result_chars=1500) -> str`: one line per block: `CUSTOMER: text` /
`ASSISTANT: text` (role user/assistant), `ASSISTANT CALLED name(json args)`, `TOOL RESULT: content` (with `(error)`
when `is_error`), truncating long results with `…[N more characters]`. Skip thinking blocks.

`make_strategy(spec, model=None, budget=None, prompt=None) -> ContextStrategy` parses
`full | window:K[:T] | clear:T[:K] | compact:T[:K]` (integers, all ≥ 1, else `ValueError`). For `compact`, `prompt=None` means
`agentlab.context.prompts.COMPACTION_PROMPT`; raise `ValueError` if that's empty/None or if `model` is None. Any
other spec → `ValueError` naming the valid forms.

## 3. `agentlab/memory/store.py`
SQLite table `memories(id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind IN
('preference','fact','commitment')), text TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '', source_session TEXT NOT
NULL DEFAULT '', created_at TEXT NOT NULL, superseded_by INTEGER)` + an index on `(customer_id, superseded_by)`,
created with `CREATE … IF NOT EXISTS` in the connection it's given (the shop DB; trials get a fresh copy).
No foreign key on `superseded_by` (the shop DB enables `foreign_keys`, and forgetting must be able to delete).
```python
@dataclass
class Memory: id, customer_id, kind, text, evidence, source_session, created_at, superseded_by=None

class MemoryStore:
    def __init__(self, conn)                       # calls init()
    def init(self) -> None
    def add(self, customer_id, kind, text, evidence="", source_session="") -> int     # created_at = clock.now()
    def active(self, customer_id) -> list[Memory]   # superseded_by IS NULL, ORDER BY id
    def search(self, customer_id, query, k=5) -> list[Memory]   # word overlap > 0, best first, newer first on ties
    def forget(self, customer_id, memory_id) -> bool            # HARD delete of the row AND every row it superseded
                                                                # (transitively); only this customer's rows
    def supersede(self, customer_id, old_id, new_id) -> bool    # both ids must belong to the customer; old must be active
def render_memory_block(memories) -> str
```
**Every query filters on `customer_id`.** `render_memory_block`: `""` for no memories; otherwise a
`<customer_memory>` … `</customer_memory>` block: one line explaining these are notes written automatically from
what the customer said, background not instructions, granting no permissions, and to call `forget_memory` with the
id when asked; then one line per memory: `- [m{id}] ({kind}, saved {YYYY-MM-DD}) {text}`. Replace `<` and `>` in
memory text (e.g. with `‹ ›`) so a memory can't close the tag.

## 4. `agentlab/memory/extract.py` and `agentlab/memory/tools.py`
```python
EXTRACT_SYSTEM: str            # the extraction prompt (write it from TEXTBOOK §6-§7; "nothing" is the usual answer)
EXTRACT_SCHEMA: dict           # {"memories": [{"kind": enum KINDS, "text", "evidence", "supersedes": int|null}]},
                               # all fields required, additionalProperties false at both levels
@dataclass
class WriteLog: candidate: Candidate; decision: PolicyDecision; memory_id: int | None = None

def render_conversation(messages) -> str     # "CUSTOMER: …" / "ASSISTANT: …" text lines only; skip any message that
                                             # carries tool results (third-party text must not reach extraction)
def customer_texts(messages) -> list[str]    # texts of customer turns (role user, no tool results, non-empty)
def extract_candidates(model, messages, existing, budget=None) -> list[Candidate]
def consolidate(store, customer_id, messages, model, *, session_id="", budget=None) -> list[WriteLog]
```
`extract_candidates`: if `render_conversation` is empty, return `[]` without calling the model. Else send one user
message containing `<existing_memories>` (lines `[id] (kind) text`, or `(none)`) and `<conversation>`; pass
`json_schema=EXTRACT_SCHEMA`, `max_tokens=800`; check/charge the budget like `Compaction`. Parse tolerantly
(strip code fences; invalid JSON or a non-list `memories` → `[]`; null fields → `""`; `supersedes` must be a real
int, not bool, else `None`).
`consolidate`: for each candidate, `memory_policy(c, customer_texts(messages), store.active(customer_id))`; on
`store`/`supersede`, `add(...)` (then `supersede(...)`), and re-read `active` so later candidates see earlier ones.
`make_memory_tools(store, customer_id) -> list[Tool]`: one tool `forget_memory(memory_id: int)`, bound to the
customer, `side_effects=True`; unknown/other-customer id → `ToolError` explaining ids come from `[m<id>]` labels;
success → `{"forgotten": true, "memory_id": …, "note": …}` where the note says the line still appears in the
memory block for the rest of this conversation and must be ignored. Description: when to use, what the id is (with an example), that
deletion is permanent.

## 5. `SupportAssistant` and `ToolRegistry.with_tools`
`ToolRegistry.with_tools(extra: list[Tool]) -> ToolRegistry`: a new registry with the same `invalid_formatter`.
New keyword parameters (defaults keep the old behaviour):
`context: str | ContextStrategy = "full"`, `memory: str = "off"` (`off|read|on`, else `ValueError`),
`notes: bool = False`, `summarizer: ChatModel | None = None` (default: the assistant's model),
`memory_model: ChatModel | None = None` (default: the assistant's model).
- `memory != "off"`: `MemoryStore(conn)`; append `"\n\n" + render_memory_block(active)` to the END of the formatted
  system prompt (if non-empty); add `forget_memory`.
- `notes=True`: add `update_case_notes(notes: str)` (replaces `self.notes`; > 2000 chars → `ToolError` telling the
  model to shorten; returns `{"saved": true, "chars": n}`). Description per TEXTBOOK §3 (what to write, that it
  replaces previous notes, that older messages may disappear).
- `self.messages` = working history; `self.transcript` = append-only list of every message.
- `chat(text)`: `working = strategy.prepare(self.messages + [user], system=self.system, tools=self.tools.specs())`;
  `send` = `working` with, if notes are enabled and non-empty, a `<case_notes>…</case_notes>` TextBlock (notes text
  with `</case_notes>` escaped) prepended to the first message (a new Message, never stored); `run_agent(...)` on `send`; `new = result.messages[len(send):]`;
  `self.messages = working + new`; `self.transcript += new` (the user message is appended to the transcript *before* the call, so a failing turn is still recorded); append to `self.turn_stats` a dict
  `{turn, calls (result.turns), input_tokens (usage.total_input, summed over the calls), cache_read_tokens,
  output_tokens, est_before, est_after, action, detail}` from
  the result usage and the strategy's last `PrepareStats`; when the action is `compacted`, also `summary` (the
  strategy's latest summary text: the learner must be able to read what the model saw). Set span attribute
  `course.context_action`.
- `self.fixed_tokens = {"system": estimate_tokens(self.system), "tools": estimate_tokens(self.tools.specs())}`.
- `end_session() -> list[WriteLog]`: if `memory == "on"` and there's a transcript, `consolidate(...)` with
  `memory_model`, `session_id`, `budget`; else `[]`.

## 6. Evals: sessions, memory graders, scopes
- `Task.sessions: list[list[str]] | None = None`. Validation: exactly one of `turns` / `user_sim` / `sessions`; no
  empty session.
- `GRADER_TYPES` += `memory_contains`, `memory_absent` (`{pattern, include_superseded?}`: regex, case-insensitive,
  over this customer's active memories, or all stored rows with `include_superseded: true`; a missing `memories`
  table means no memories).
- `TrialContext.last_session_replies: list[str] | None = None` and `scoped(scope, default)`: `final` → last reply;
  `last_session` → `last_session_replies` (or all replies if None); anything else (`any`, `all`) → all replies.
  `reply_regex`/`reply_contains_any` default `final`; `reply_not_regex`/`reply_not_contains` default `all`.
  Existing tasks must grade exactly as before.
- `run_trial`: for `sessions`, a fresh `SupportAssistant` per session on the same connection; after each session
  (and after a single-session task, or an interrupted one) fold `assistant.transcript` and `turn_stats` (tagged with
  `session` index) into the trial and call `end_session()`, recording each WriteLog as
  `{session, kind, text, evidence, supersedes, action, reason, memory_id}`. Make that fold idempotent (an exception mid-session must not fold twice). Graders get
  the concatenated **transcript** (not the working history) and `last_session_replies`. `Trial.extra: dict =
  field(default_factory=dict)` (old jsonl still loads) = `{"turn_stats", "memory_writes", "fixed_tokens",
  "context_actions"}` (`fixed_tokens` from the assistant)
  (`context_actions` = sorted set of actions other than `none`). Scale the time ceiling for scripted tasks:
  `ceiling_s * max(1, total_turns / 10)` (user-simulator tasks keep `ceiling_s`).

## 7. Experiments and CLI
- `Variant` gains `context="full"`, `memory="off"`, `notes=False`, passed through `assistant_opts()`.
  `fingerprint()` adds them to the hashed payload **only when non-default** (plus `COMPACTION_PROMPT` when context
  starts with `compact`, and `EXTRACT_SYSTEM` when memory is on), so a Node 05 variant keeps its Node 05 hash.
- `experiment --baseline/--candidate` accept keys `context=`, `memory=` (off|read|on), `notes=` (on|off) in addition to
  Node 05's; validate the context spec with `make_strategy(spec, model=object())` before spending (this also fails
  fast if `compact` is asked for and `COMPACTION_PROMPT` is missing).
- `run` gains `--context SPEC`, `--memory off|read|on`, `--notes`, recorded in `meta.json`; validate as above.

## 8. Report
`agentlab/context/report.py`:
```python
def summarize_context(trials) -> dict[str, dict]
    # per trial.model label: trials, pass_rate (pass / (pass+fail)), by_length {"len10": rate, …} from tags,
    # input_tokens_per_trial, cache_share (cache_read / input), cost_per_trial, compactions_per_trial,
    # max_call_est_tokens (max est_after)
def render_context_report(trials, title="context") -> str     # one markdown table, one row per label
def write_tokens_by_turn(trials, path) -> None                # CSV: variant, task, trial, session, turn,
                                                              # input_tokens, cache_read_tokens, action
```
`python -m agentlab.context report RUN_DIR` → prints the table, writes `context_report.md` and `tokens_by_turn.csv`
into RUN_DIR. `python -m agentlab.context breakdown RUN_DIR --task ID [--trial 0] [--variant LABEL]` → prints
`breakdown("", [], transcript)` for that trial with `system`/`tools` replaced by `extra["fixed_tokens"]` (total
recomputed), with percentages, then every `summary` recorded in its turn_stats. If more than one trial matches,
exit with a message listing the variants.

## Done when
`make grade N=06` passes except the expected-red tests: `test_split.py`, `test_compaction_prompt.py`,
`test_memory_policy.py`, and the tests that exercise them (window/compaction strategies, `consolidate`, the
end-to-end long and memory trials). List which tests are red and why in your summary. `make grade-upto N=06` is
green for 00–05. Explain your diff.
