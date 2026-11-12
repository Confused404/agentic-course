# SPEC: Node 01, `agentlab/probe`: a measurement harness for raw model calls

**For the coding agent.** Implement exactly this. Read `AGENTS.md` first. Background: TEXTBOOK §2–§4, §9.
`agentlab/probe/toy_sampler.py` is **AGENT-OFF**. Do not implement it, even if tests for it fail.

## Purpose
The experiments in `nodes/01-llm-internals/experiments/` (already written, don't modify them) call
providers through their **raw SDKs** and record what happened: tokens, timings, cost, outputs, tool calls.
This package is the library they import. It deliberately does **not** use `agentlab.llm` adapters
(those come in Node 02); seeing raw formats is the point of this node.

Design principle: **separate I/O from parsing.** `parse.py` is pure functions over plain dicts (easy
to test with recorded payloads). `raw.py` does network I/O and timing, then hands dicts to `parse.py`.

## Files to create
```
agentlab/probe/__init__.py      re-export the public names below
agentlab/probe/results.py
agentlab/probe/parse.py
agentlab/probe/raw.py
agentlab/probe/haystack.py
```

### 1. `results.py`
```python
@dataclass
class ProbeResult:
    experiment: str
    provider: str
    model: str
    label: str = ""                       # free-form group label, e.g. "len=8000" or "T=0.7"
    params: dict = field(default_factory=dict)
    input_tokens: int = 0                 # uncached input
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    ttft_s: float | None = None
    total_s: float = 0.0
    cost_usd: float | None = None
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    stop_reason: str = ""
    error: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def output_tps(self) -> float | None: ...
        # output_tokens / (total_s - ttft_s) when ttft_s is not None and the denominator > 0, else None

def append_jsonl(path: str | Path, result: ProbeResult) -> None   # creates parent dirs; one JSON object per line
def load_jsonl(path: str | Path) -> list[ProbeResult]
def summarize(results: list[ProbeResult], group_by: list[str], metrics: list[str]) -> list[dict]
def print_table(rows: list[dict], title: str = "") -> None          # rich.table; floats to 4 significant digits
```
`summarize` semantics (tested):
- `group_by` keys name a ProbeResult field (`"model"`, `"label"`) **or** a param as `"params.<key>"`.
- Output: one dict per group, in first-seen order, containing the group keys plus `n` (results in the group,
  errors included), `errors` (count with `error` set), and for each metric `m`: `m_mean`, `m_std` (sample
  std, 0.0 if fewer than 2 values), `m_p50`, `m_p90` (nearest-rank percentiles).
- A metric may be a field (`"ttft_s"`), a property (`"output_tps"`), or `"extra.<key>"`. **None values and
  results with `error` are excluded** from metric statistics. If no values remain, the stats are None.

### 2. `parse.py` (pure; no network, no SDK imports)
Both functions return `{"text": str, "tool_calls": list[dict], "stop_reason": str, "usage": Usage, "model": str}`
where each tool call dict is `{"id", "name", "arguments": dict | None, "raw_arguments": str | None, "parse_error": str | None}`.

```python
def parse_anthropic(msg: dict) -> dict
```
- `msg` is a Messages API response as a dict (`message.model_dump()`).
- text = concatenation of `text` blocks; `tool_use` blocks become tool calls with `arguments = block["input"]`,
  `raw_arguments = None`. `thinking` blocks are ignored here (count is in usage).
- Usage: `input_tokens`, `output_tokens`, `cache_read_tokens = cache_read_input_tokens or 0`,
  `cache_write_tokens = cache_creation_input_tokens or 0`,
  `reasoning_tokens = (usage.output_tokens_details or {}).get("thinking_tokens") or 0`. Any field may be missing or null.

```python
def parse_openai(completion: dict) -> dict
```
- `completion` is a Chat Completions response as a dict. Use `choices[0]`.
- text = `message.content or ""`. Each `message.tool_calls[i]` becomes a tool call; `raw_arguments` is the
  `function.arguments` string; `arguments` is `json.loads(raw)` **or None with `parse_error` set to the
  exception message** if it fails or isn't a JSON object. A `None` or empty `""` argument string (a tool with
  no parameters) means `arguments = {}` with no error. Never raise on bad arguments.
- `stop_reason = finish_reason`, except: if there are tool calls, report `"tool_calls"` regardless (some local
  runtimes say `"stop"` even with tool calls; record the original in `extra` of the ProbeResult, see raw.py).
- Usage: `cached = usage.prompt_tokens_details.cached_tokens or 0` (fields may be missing or null);
  `input_tokens = prompt_tokens - cached`, `cache_read_tokens = cached`, `output_tokens = completion_tokens`,
  `reasoning_tokens = completion_tokens_details.reasoning_tokens or 0`, `cost_usd = usage.cost` if present.
  Missing `usage` → all zeros.

### 3. `raw.py` (network I/O)
```python
def anthropic_call(model: str, *, system: str | list[dict], messages: list[dict], budget: Budget,
                   experiment: str, label: str = "", tools: list[dict] | None = None,
                   max_tokens: int = 512, stream: bool = True, save_raw: Path | None = None,
                   client=None, **extra) -> ProbeResult

def anthropic_count_tokens(model: str, *, system: str | list[dict], messages: list[dict],
                           tools: list[dict] | None = None, client=None) -> int

def openai_compat_call(provider: str, model: str, *, system: str, messages: list[dict], budget: Budget,
                       experiment: str, label: str = "", tools: list[dict] | None = None,
                       max_tokens: int = 512, stream: bool = True, save_raw: Path | None = None,
                       client=None, **extra) -> ProbeResult
```
Requirements:
- `client=None` → construct the SDK client from `agentlab.config` (`api_key`, `provider_config`). Tests inject a
  fake client.
- `system`, `messages`, `tools` are in **that vendor's** native format (the experiments build them). For
  OpenAI-compatible calls, prepend `{"role": "system", "content": system}` to messages.
- `**extra` is passed straight to the SDK call (e.g. `output_config=`, `thinking=`, `cache_control=`,
  `diagnostics=` for Anthropic; `temperature=`, `seed=`, `reasoning_effort=` for OpenAI-compatible). Record
  `extra` in `ProbeResult.params`.
- **Timing:** `total_s` wall-clock around the whole call. With `stream=True` record two times (TEXTBOOK §3:
  for reasoning models, visible output starts only after thinking):
  - `ttft_s`: first **visible** delta. Anthropic: first `content_block_delta` event whose `delta.type` is
    `text_delta` or `input_json_delta`. OpenAI: first chunk whose delta has `content` or `tool_calls`.
  - `extra["ttft_any_s"]`: first delta of **any** kind, including thinking/reasoning (Anthropic: any
    `content_block_delta`; OpenAI: also `delta.reasoning` or `delta.reasoning_content`).
  With `stream=False`, `ttft_s=None` and no `ttft_any_s`.
- **Anthropic streaming:** use `client.messages.stream(...)` as a context manager, iterate events for timing,
  then `get_final_message().model_dump()` → `parse_anthropic`.
- **OpenAI streaming:** `stream=True, stream_options={"include_usage": True}`. Accumulate content and tool-call
  fragments by `index` (name and id arrive once, `arguments` arrive in pieces), and take usage from the chunk
  that carries it. Rebuild a completion-shaped dict and pass it to `parse_openai`. If the runtime sends no
  usage, leave zeros and set `extra["usage_missing"] = True`.
- Put the response `id` in `extra["message_id"]`, the original finish/stop reason in `extra["raw_stop_reason"]`,
  and any top-level `diagnostics` field of an Anthropic response in `extra["diagnostics"]`.
- **Budget:** after a successful call, `cost = budget.charge(model, usage, provider=provider)` and store it in `cost_usd`.
  `BudgetExceeded` must propagate (never swallow it). Any *other* exception → return a ProbeResult with
  `error=f"{type(e).__name__}: {e}"` (experiments keep going).
- **Tracing:** wrap each call in `agentlab.tracing.chat_span(provider, model)` and set token/cost attributes
  (see `tracing.record_response` for names; you can't call it directly because you don't have a
  ModelResponse here, so set the same attributes).
- `save_raw`: if given, write `{"request": {...kwargs except client...}, "response": <final dict>}` as indented JSON.
- `anthropic_count_tokens` calls `client.messages.count_tokens(...)` and returns `.input_tokens`. Omit `system`
  (and `tools`) from the call when empty: the API rejects an empty system string.

### 4. `haystack.py`
```python
def build_haystack(target_tokens: int, needle: str, position: float, distractors: list[str] = (),
                   seed: int = 0, corpus_dir: Path = ROOT / "data" / "help_center") -> str
def ops_memo(rng: random.Random) -> str                # one synthetic, unique-looking paragraph
def needle_position(text: str, needle: str) -> float   # char offset of needle / len(text); -1.0 if absent
def estimate_tokens(text: str) -> int                  # len(text) // 4
```
- Help-center paragraphs = the bodies of `corpus_dir/*.md` **in sorted filename order** (strip front-matter
  between the first two `---` lines), split on blank lines, empty ones dropped. Shuffle with `random.Random(seed)`.
- Filler: take the shuffled help-center paragraphs in order, each **once**. When they run out, append
  `ops_memo(rng)` paragraphs (same rng). **Never repeat a paragraph** (skip duplicates). Stop as soon as
  `estimate_tokens` of the joined filler is ≥ `target_tokens`.
- `ops_memo`: at least 5 templates of realistic internal notes (warehouse receipts, shift notes, vendor price
  changes, IT notices…) mixing dates, city names and 4-digit numbers. These are deliberately needle-like:
  realistic long contexts are full of near-miss facts.
- Then insert each distractor at `rng.randint(0, len(filler))` (in order), and **then** the needle at index
  `round(position * len(list))` (so 0.0 is exactly first and 1.0 exactly last). Join with `"\n\n"`.
- Deterministic: same args → same string.

## Done when
`make grade N=01` passes **except** `test_toy_sampler.py` (that one is the learner's). Report the result and
list anything in this SPEC you found ambiguous.
