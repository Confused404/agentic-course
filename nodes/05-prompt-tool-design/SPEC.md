# SPEC: Node 05: lint for tools and prompts, tool variants, and an experiment runner

**For the coding agent.** Read `AGENTS.md`. Background: TEXTBOOK §2–§6.
**AGENT-OFF (the learner's):**
- `SYSTEM_PROMPT_V2` in `agentlab/assistant/prompts.py`: you add the registry around it; never write or edit its text.
- `docs/design/support-tools-v2.md`: the learner's design for the v2 tools (descriptions, schemas, return shapes,
  error messages). **You implement exactly what that document says.** If it's missing or ambiguous, stop and ask; don't
  invent the design.
Tests that check the learner's prompt and design (`test_prompt_v2.py`, `test_tools_v2.py`) stay red until those exist.

## Files
```
create  agentlab/tools/lint.py
modify  agentlab/assistant/prompts.py         registry only (2)
modify  agentlab/tools/base.py                ToolRegistry(invalid_formatter=...) (3)
modify  agentlab/assistant/tools.py           variants v2 and v1+<feature> (3)
modify  agentlab/assistant/support.py         tool_variant parameter (3)
create  agentlab/evals/experiment.py          (4)
modify  agentlab/evals/__main__.py            `experiment` and `lint` subcommands (5)
```

## 1. `agentlab/tools/lint.py`
```python
@dataclass
class Finding:
    level: str            # "error" | "warning"
    where: str            # tool name, "prompt", or "tools"
    rule: str             # short id, e.g. "param-no-description"
    message: str

def lint_tools(specs: list[ToolSpec]) -> list[Finding]
def lint_prompt(text: str, required_placeholders: tuple[str, ...] = ("{today}",)) -> list[Finding]
```
`lint_tools` rules (rule id → level):
| rule | level | when |
|---|---|---|
| `name-format` | error | name doesn't match `^[a-z][a-z0-9_]{1,63}$` |
| `duplicate-name` | error | two tools share a name |
| `desc-too-short` | error | description shorter than 40 characters |
| `schema-not-object` | error | `input_schema.type != "object"` |
| `param-no-type` | error | a property without `"type"` |
| `required-unknown` | error | a `required` name not in `properties` |
| `desc-no-when` | warning | description lacks a "when to use" cue (`\b(use|when|only after|before)\b`, case-insensitive) |
| `desc-no-returns` | warning | description doesn't say what it returns (`\breturn`) |
| `param-no-description` | warning | a property without `"description"` |
| `categorical-no-enum` | warning | a string property named `reason`, `status`, `type`, `kind`, `category`, `priority` (or ending `_type`/`_status`) without `enum` |
| `number-no-unit` | warning | an integer/number property whose name contains `amount`, `price`, `cost`, `total`, `timeout`, `duration`, `delay` but doesn't end with a unit (`_cents`, `_usd`, `_dollars`, `_s`, `_ms`, `_seconds`, `_minutes`, `_days`) |
| `additional-properties` | warning | `additionalProperties` is not `false` |
| `confusable-names` | warning | two names where one is a prefix of the other, or their edit distance is ≤ 2 |
| `tools-too-long` | warning | `len(json.dumps([all specs])) / 4 > 4000` (estimated tokens) |
`lint_prompt` rules:
| rule | level | when |
|---|---|---|
| `missing-placeholder` | error | a required placeholder is absent |
| `shouting` | warning | more than 3 ALL-CAPS words of ≥ 4 letters (ignore words inside `{…}`, tool names, and the common acronyms in `ACRONYMS`: JSON, HTTP(S), HTML, USPS, UTC, API, URL, SKU, FAQ, USD, CAD, ISO) |
| `absolutes` | warning | more than 6 occurrences of `never|always|must` (case-insensitive, whole words) |
| `too-long` | warning | estimated tokens (`len/4`) > 2000 |
| `volatile-early` | warning | any required placeholder first appears in the first 20% of the text (breaks the cacheable prefix, TEXTBOOK §2) |

## 2. Prompt registry (`agentlab/assistant/prompts.py`)
Add, without touching any prompt text:
```python
PROMPTS: dict[str, str]          # {"v1": SYSTEM_PROMPT_V1, "v2": SYSTEM_PROMPT_V2 (if defined)}
def get_prompt(name: str) -> str # KeyError listing available names
```
If `SYSTEM_PROMPT_V2` isn't defined yet, `PROMPTS` has only `v1`.

## 3. Tool variants: v2 and its single-feature parts
`make_support_tools(conn, customer_id, actor="agent:support", variant: str = "v1")`. A variant string is `v1`, `v2`, or
`v1+<feature>[+<feature>...]` with features from `FEATURES = ("desc", "errors", "returns")`; `v2` ≡ all three. Add
`parse_variant(variant) -> set[str]` that raises `ValueError` on anything else (`v1+vibes`, `v2+desc`, `v3`).
The three features are separable so each can be tested as **one change** (YOU_DO task 4):
| feature | what changes (all text comes from `docs/design/support-tools-v2.md`) |
|---|---|
| `desc` | tool descriptions and parameter descriptions/enums/`additionalProperties: false` |
| `errors` | `ShopError` and argument-validation errors become the design doc's JSON error shape |
| `returns` | return values gain the derived fields the doc specifies (e.g. dollars next to cents) |
Hard constraints (the eval suite depends on them):
- **Same tool names and parameter names as v1** (Node 04 graders and golden scripts reference them). New tools or
  *optional* parameters are fine.
- Same bindings: no tool accepts a customer id; same `services` calls underneath (policy stays enforced in code).
- For `v2`: `lint_tools(registry.specs())` returns **no errors and no warnings**.
- Every v2 description and parameter description appears **verbatim** (whitespace-insensitive) in the design doc;
  `test_tools_v2.py` checks this. You implement the doc; you don't edit the text.
- Errors (`errors` feature): catch `ShopError` and raise `ToolError(json.dumps({"error": CODE, "message": ...,
  "next_steps": [...]}))` so the registry marks it `is_error=True`. `CODE` is UPPER_SNAKE (the service's code or a
  finer one from the doc); `message` is the service message plus the doc's text; `next_steps` has ≥ 1 entry.
- Argument-validation errors must use the same shape. Add an optional
  `ToolRegistry(tools, invalid_formatter: Callable[[str, list[str]], str] | None = None)`; when set, `execute` returns
  `invalid_formatter(tool_name, problems)` as the error content instead of the plain-text message. Default unchanged.
`SupportAssistant(..., tool_variant: str = "v1")` passes it to `make_support_tools`.

## 4. `agentlab/evals/experiment.py`
```python
MIN_TASKS = 8

@dataclass
class Variant:
    name: str
    prompt: str = "v1"          # key in PROMPTS
    tools: str = "v1"           # tool variant string (3)
    model_opts: dict = field(default_factory=dict)

    def assistant_opts(self) -> dict    # {"system_prompt": get_prompt(prompt), "tool_variant": tools, "model_opts": {...}}
    def fingerprint(self) -> str        # sha256[:8] of json.dumps({prompt text, tool specs, model_opts}, sort_keys=True)

@dataclass
class ExperimentResult:
    baseline: list[Trial]
    candidate: list[Trial]
    comparison: dict            # report.compare over the combined trials: {"tasks", "diff", "lo", "hi"}
    by_tag: dict[str, tuple[float | None, float | None]]     # tag -> (baseline rate, candidate rate)
    verdict: str
    by_split: dict[str, dict] = {}     # split -> compare(...) for that split's trials + its own "verdict"
    partial: bool = False              # True if a BudgetExceeded stopped the run early
    margin: float = 0.05

def run_experiment(tasks, model_factory, baseline: Variant, candidate: Variant, *, template_db: Path, trials: int = 3,
                   budget: Budget | None = None, judge_factory=None, sim_factory=None, margin: float = 0.05,
                   out_dir: Path | None = None) -> ExperimentResult
def append_log(path: Path, *, hypothesis: str, change: str, model: str, result: ExperimentResult,
               decision: str = "", hashes: tuple[str, str] = ("", "")) -> None
```
Verdict, in this order: `insufficient` if fewer than `MIN_TASKS` tasks (a bootstrap over a handful of tasks gives
intervals too narrow to trust); `better` if `lo > 0`; `worse` if `hi < 0`; `non-inferior` if `lo > -margin`;
otherwise `inconclusive`.
`run_experiment`: for each trial index, for each task, run both variants (`run_trial` with each `assistant_opts()`,
labels `baseline`/`candidate`), **alternating which goes first** on `(k + i) % 2` so drift doesn't favour one side.
Keep only complete pairs. If `out_dir` is given, append each trial to `out_dir/trials.jsonl` as it finishes. On
`BudgetExceeded`, stop, set `partial=True`, and analyse the complete pairs so far; if there are none, raise
`RuntimeError`. `append_log` creates the file with this header if missing, then appends one row:
`| date | model | change | hypothesis | baseline [hash] | candidate [hash] | tasks × trials | diff [lo, hi] | verdict | decision |`
(task means from `report.summarize` as 0-decimal percentages; diff in signed points; verdict suffixed ` (partial)`
when partial; escape `|` and remove newlines in free-text cells).

## 5. CLI additions (`python -m agentlab.evals`)
```
experiment --suite PATH --model ALIAS --baseline prompt=v1,tools=v1 --candidate prompt=v1,tools=v1+desc
           [--split dev|heldout|all] [--tags a,b] [--trials 3] [--budget 2] [--margin 0.05]
           [--hypothesis TEXT] [--change TEXT] [--decision TEXT]
           [--log docs/experiments/node05.md] [--judge ALIAS] [--sim ALIAS]
run ... [--prompt v1] [--tools v1]           # existing subcommand: pick a prompt by name (get_prompt) and a tool variant
lint [--tools v1|v2|v1+desc...] [--prompt v1|v2]     # prints findings; exit code 1 if any error
```
`--baseline/--candidate` parse comma-separated `key=value` pairs strictly: keys are `prompt`, `tools`, or
`opt.<model option>` (value parsed as JSON when possible: `opt.parallel_tools=false` → `False`, `opt.effort="low"`);
anything else exits with a message. Validate the tool variant and prompt name before spending anything. Save
`runs/experiments/<timestamp>/{trials.jsonl, meta.json}` (meta: resolved model, both variant strings, both
fingerprints, git sha, split, tags, trials). The log path is relative to the repo root. Print the comparison, the
by-split and by-tag tables, and the verdict.

## Done when
`make grade N=05` passes except `test_prompt_v2.py` and `test_tools_v2.py`, which need the learner's prompt and design
document (and then your v2 implementation of that document). Explain your diff.
