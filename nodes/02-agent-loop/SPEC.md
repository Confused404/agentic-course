# SPEC: Node 02: adapters, tools, the support assistant, and a mini eval runner

**For the coding agent.** Read `AGENTS.md` first. Background: TEXTBOOK §2–§8.
**AGENT-OFF:** `agentlab/agent/loop.py::run_agent` is the learner's. Don't implement it, don't write a
substitute loop anywhere. The assistant (5) *calls* `run_agent`. Its tests stay red until the learner
writes the loop; that's expected (AGENTS.md rule 10). Don't modify `agentlab/llm/types.py` or `fake.py`.

## Files to create
```
agentlab/tools/__init__.py           re-export Tool, ToolRegistry, validate_args
agentlab/tools/base.py
agentlab/llm/anthropic_adapter.py
agentlab/llm/openai_compat.py
agentlab/assistant/__init__.py
agentlab/assistant/prompts.py
agentlab/assistant/tools.py
agentlab/assistant/support.py
agentlab/evals/__init__.py
agentlab/evals/mini.py
```
And modify `shopfront/app.py` (the `/api/assistant/chat` endpoint only).

---

## 1. `agentlab/tools/base.py`
```python
@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict          # JSON Schema object
    fn: Callable[..., Any]      # called as fn(**validated_input)
    side_effects: bool = False  # informational for now; Node 13 uses it

def validate_args(schema: dict, args: dict) -> list[str]   # human-readable problems; [] if valid

class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None           # duplicate names -> ValueError
    def specs(self) -> list[ToolSpec]                         # SORTED BY NAME (cache stability, Node 01 §3)
    def names(self) -> list[str]                              # sorted
    def execute(self, call: ToolUseBlock) -> ToolResultBlock  # never raises
```
`validate_args` supports the subset the course uses: `type: object` with `properties`, `required`, and
`additionalProperties: false`; property `type` of `string`, `integer` (bool is **not** an integer), `number`
(int or float, not bool), `boolean`, `array` (with `items` validated one level), `object`; `enum`; `minimum`/`maximum`
for numbers; `minLength`/`maxLength` for strings. Messages name the field and the expectation,
e.g. `"order_id: expected integer, got str '4821'"`, `"missing required field 'reason'"`,
`"reason: must be one of ['damaged', ...], got 'broken'"`, `"unexpected field 'customer_id'"`.

`execute` semantics:
- unknown name → `is_error=True`, content `"Unknown tool 'X'. Available tools: a, b, c."`
- validation problems → `is_error=True`, content `"Invalid arguments for X: " + "; ".join(problems)`
- `fn` raises `shopfront.services.ShopError` → `is_error=True`, content `json.dumps(e.to_dict())`
- `fn` raises anything else → `is_error=True`, content `"Tool X failed: <ExceptionType>: <message>"`
  (don't include a traceback)
- success → content is the return value: `str` as is; anything else `json.dumps(value, sort_keys=True, default=str)`.
- Always set `tool_use_id=call.id`.

## 2. `agentlab/llm/anthropic_adapter.py`
```python
def to_anthropic_request(*, model: str, system: str | list[TextBlock], messages: list[Message],
                         tools: list[ToolSpec] | None, max_tokens: int, opts: dict) -> tuple[dict, list[str]]
    # returns (request_kwargs, dropped_opt_names)
def from_anthropic_response(data: dict, latency_s: float = 0.0) -> ModelResponse
class AnthropicModel:      # implements ChatModel
    provider = "anthropic"
    def __init__(self, model: str, api_key: str | None = None, client=None): ...
    last_dropped_opts: list[str]          # set on every call
    def complete(self, *, system, messages, tools=None, max_tokens=1024, **opts) -> ModelResponse
```
Request mapping:
- `system`: a str is passed as is (omitted if empty). A list of TextBlocks → `[{"type":"text","text":...}]`, adding
  `"cache_control": {"type": "ephemeral"}` to blocks with `cache=True`.
- Message blocks:
  `TextBlock` → `{"type":"text","text"}` (+cache_control if `cache`);
  `ImageBlock` → `{"type":"image","source":{"type":"base64","media_type":...,"data":...}}`;
  `ToolUseBlock` → `{"type":"tool_use","id","name","input"}`;
  `ToolResultBlock` → `{"type":"tool_result","tool_use_id","content": <str or list of mapped text/image blocks>,"is_error"}`;
  `ThinkingBlock` with `provider == "anthropic"`: if `provider_data` has `redacted_data` →
  `{"type":"redacted_thinking","data": ...}`, else `{"type":"thinking","thinking": text, "signature": provider_data["signature"]}`;
  `ThinkingBlock` from any other provider → **dropped**.
- `tools` → `[{"name","description","input_schema"}]` in the given order (omit key if no tools).
- opts: `effort` → `output_config.effort`; `json_schema` → `output_config.format = {"type":"json_schema","schema": ...}`;
  `tool_choice`: `"auto"|"any"|"none"` → `{"type": same}`, `{"name": n}` → `{"type":"tool","name":n}`;
  `thinking` (dict) → passed through; `cache: True` → top-level `cache_control: {"type":"ephemeral"}`;
  `parallel_tools: False` → `tool_choice.disable_parallel_tool_use = True` (with `{"type":"auto"}` if no tool_choice given).
  `ThinkingBlock`s without a signature are dropped. If a message ends up with no blocks, send
  `[{"type":"text","text":"(no content)"}]` (the API rejects empty content).
  **Any other opt (e.g. `temperature`, `top_p`, `seed`) is dropped** and its name returned in the dropped list.
Response mapping:
- `text` → TextBlock; `tool_use` → `ToolUseBlock(id, name, input, provider="anthropic")`;
  `thinking` → `ThinkingBlock(thinking, provider="anthropic", provider_data={"signature": ...})`;
  `redacted_thinking` → `ThinkingBlock("", provider="anthropic", provider_data={"redacted_data": data})`; other types ignored.
- stop_reason: `end_turn, tool_use, max_tokens, stop_sequence, refusal, pause_turn` map to themselves;
  `model_context_window_exceeded` → `context_window_exceeded`; anything else → `other`. Keep the original in `raw_stop_reason`.
- usage: like Node 01's `parse_anthropic` (uncached input, output, cache read/write, `output_tokens_details.thinking_tokens`).
- `id`, `model`, `provider="anthropic"`, `latency_s`, `raw=data`.
`complete`: build the request, `client.messages.create(**req)`, `.model_dump()`, map. Measure latency. Let SDK
exceptions propagate (Node 14 adds retry policy). Construct the client lazily from `agentlab.config` if not injected.

## 3. `agentlab/llm/openai_compat.py`
```python
def to_openai_request(*, model: str, system: str | list[TextBlock], messages: list[Message],
                      tools: list[ToolSpec] | None, max_tokens: int, opts: dict,
                      provider: str) -> tuple[dict, list[str]]
def from_openai_response(data: dict, provider: str, latency_s: float = 0.0) -> ModelResponse
class OpenAICompatModel:   # implements ChatModel; works for openrouter, ollama, openai
    def __init__(self, model: str, base_url: str, api_key: str | None, provider: str, client=None): ...
    last_dropped_opts: list[str]
    def complete(self, *, system, messages, tools=None, max_tokens=1024, **opts) -> ModelResponse
```
Request mapping (TEXTBOOK §4 table):
- First message `{"role":"system","content": <system text; blocks joined with "\n\n">}` (omit if empty).
- Assistant message → `{"role":"assistant","content": <joined text or None>}` (use `""` instead of None when there are
  no tool calls either) plus, if it has tool calls,
  `"tool_calls": [{"id","type":"function","function":{"name", "arguments": raw_arguments if parse_error else json.dumps(input)}}]`.
  ThinkingBlocks: if `provider == <this provider>` and `provider_data` has `reasoning_details`, set
  `"reasoning_details"` on the assistant message to that value; otherwise drop.
- User message: first, each `ToolResultBlock` → `{"role":"tool","tool_call_id": id, "content": text}` where text is
  `block.text`, prefixed `"ERROR: "` if `is_error`. Then the remaining text/image blocks (plus any images that were
  inside tool results) as ONE `{"role":"user", ...}` message: `content` is a plain string if only text, else a list of
  `{"type":"text","text"}` / `{"type":"image_url","image_url":{"url":"data:<media_type>;base64,<data>"}}` parts.
  Omit that user message if it would be empty.
- tools → `[{"type":"function","function":{"name","description","parameters": input_schema}}]`.
- `max_tokens` → `max_tokens`, except `provider == "openai"` → `max_completion_tokens` (OpenAI deprecated `max_tokens`
  and its reasoning models reject it; OpenRouter and Ollama accept it).
- opts: `effort` → `reasoning_effort`, except on OpenRouter → `extra_body["reasoning"] = {"effort": v}` (its unified
  reasoning control); `parallel_tools` → `parallel_tool_calls=bool(v)`; `temperature`, `top_p`, `seed` → passed through
  (note: OpenAI reasoning models reject them on OpenAI directly, and OpenRouter drops them silently); `json_schema` →
  `response_format={"type":"json_schema","json_schema":{"name":"output","schema": ..., "strict": True}}` (strict mode needs
  `additionalProperties: false` and every property listed in `required`; that's the caller's job);
  `tool_choice`: `"auto"`/`"none"` → same, `"any"` → `"required"`, `{"name": n}` → `{"type":"function","function":{"name": n}}`;
  `cache` → dropped **and reported** (caching is automatic on these providers); `fallback_models` (a list of model
  ids) → on OpenRouter `extra_body["models"] = [model, *fallback_models]` (its server-side fallback: the model registry
  adds this for free models, see `agentlab/llm/pacing.py`), elsewhere dropped and reported. Other opts dropped and
  reported.
- If `provider == "openrouter"`: also put `"usage": {"include": True}` in `extra_body` so cost comes back.
Response mapping:
- `choices[0].message`: non-empty `content` → TextBlock. Each `tool_calls[i]` → ToolUseBlock with `input` parsed from the
  arguments string; on failure (or non-object JSON) `input={}`, `raw_arguments=<string>`, `parse_error=<message>`;
  empty/None arguments → `{}`. If a tool call has no `id`, generate one that is unique across turns and starts with
  `"call_"` (e.g. `f"call_{uuid4().hex[:8]}_{i}"`). Set `provider=<provider>`.
- Reasoning: if the message has `reasoning_details` → prepend `ThinkingBlock(message.get("reasoning") or "",
  provider=<provider>, provider_data={"reasoning_details": ...})`; elif it has `reasoning` or `reasoning_content` text →
  prepend `ThinkingBlock(text, provider=<provider>)`.
- stop: if there are tool calls → `tool_use` (regardless of finish_reason); else `stop`→`end_turn`, `length`→`max_tokens`,
  `content_filter`→`content_filter`, otherwise `other`. Keep the original in `raw_stop_reason`.
- usage like Node 01 `parse_openai`; `id`, `model` (the response's, possibly ""), `provider`, `latency_s`, `raw`.
`complete`: `client.chat.completions.create(**req).model_dump()`, map, then if the response model is empty set it to the
requested model. Lazy client from config if not injected.

## 4. `agentlab/assistant/prompts.py`
Put this exact text in `SYSTEM_PROMPT_V1` (the learner improves it in Node 05; don't "improve" it now):
```
You are Shopfront's customer support assistant. You are talking with a signed-in customer.
Today's date is {today}.

Use the tools to look things up; never guess order details, dates or policy. Policy facts come from
the help center (search_help_center) and from check_refund_eligibility, which applies the official rules.

Refunds: check eligibility first, using the reason that matches what the customer said. If eligible and the
customer has asked for a refund, issue it for the full refundable amount unless they asked for less.
If not eligible, explain why in one or two sentences and offer what is possible.
Escalate to a human (escalate_to_human) for lost packages, warranty claims, safety issues, or anything you
cannot resolve with your tools. Only discuss this customer's own orders.

Be concise and friendly. Amounts are in cents in tools; show dollars to the customer.
```
`{today}` is filled with `shopfront.clock.now().date().isoformat()`.

## 5. `agentlab/assistant/tools.py`
```python
def make_support_tools(conn: sqlite3.Connection, customer_id: int, actor: str = "agent:support") -> ToolRegistry
def search_help_center(query: str, k: int = 3, root: Path = ROOT / "data" / "help_center") -> list[dict]
```
Every tool is **bound** to `conn`, `customer_id` and `actor` via closures (TEXTBOOK §5). No tool takes a customer id.
| name | input | calls | side_effects |
|---|---|---|---|
| `get_my_orders` | `limit` (integer 1–20, optional, default 10) | `services.list_orders_for_customer(conn, customer_id, limit)` | no |
| `lookup_order` | `order_id` (integer) | `services.get_order(conn, order_id, customer_id=customer_id)` | no |
| `check_refund_eligibility` | `order_id` (integer), `reason` (enum of `services.REFUND_REASONS`) | `services.refund_eligibility(..., customer_id=customer_id)` | no |
| `issue_refund` | `order_id`, `amount_cents` (integer ≥ 1), `reason` (enum) | `services.issue_refund(..., actor=actor, customer_id=customer_id)` | yes |
| `cancel_order` | `order_id` | `services.cancel_order(conn, order_id, actor, customer_id)` | yes |
| `escalate_to_human` | `summary` (string, minLength 10), `order_id` (integer, optional) | `services.escalate_to_human(conn, customer_id, summary, order_id, actor)` | yes |
| `search_help_center` | `query` (string, minLength 2) | `search_help_center(query)` | no |

All schemas set `additionalProperties: false`. Write each description in 1–3 sentences saying what it does, when to
use it, and what it returns. `search_help_center`: score each article by the number of distinct lowercase query words
(≥ 3 letters) appearing in its text; return the top `k` with score > 0 as
`{"slug", "title", "status", "updated", "excerpt"}` (excerpt = body without front-matter, first 700 chars), sorted by
score descending then slug. Include archived articles (Node 07 deals with that).

## 6. `agentlab/assistant/support.py`
```python
@dataclass
class AssistantReply:
    reply: str
    result: LoopResult

class SupportAssistant:
    def __init__(self, model: ChatModel, conn: sqlite3.Connection, customer_id: int,
                 budget: Budget | None = None, max_turns: int = 8, model_opts: dict | None = None)
    messages: list[Message]          # conversation history across chat() calls
    def chat(self, user_text: str) -> AssistantReply
```
`chat` appends `Message.user(user_text)`, calls `run_agent(model, system, self.messages, tools,
LoopConfig(max_turns, budget=budget, agent_name="support", model_opts=...))`, stores `result.messages` as the new
history, and returns the reply. Reply = the loop's final text if the stop was `end_turn` or `refusal`; for any other
stop, reply `FALLBACK_REPLY = "Sorry, I couldn't finish that. Please try again, or ask me to connect you with our
support team."` (after `max_turns`/`budget` the last text is usually a preamble, and the reply must not claim anything
was recorded). Never an empty string. Expose `customer_id` as an attribute.

## 7. `agentlab/evals/mini.py`
```python
@dataclass
class Case:
    id: str
    customer_id: int
    turns: list[str]           # user messages, sent in order (each is one chat() call)
    expect: dict
    note: str = ""

@dataclass
class CaseResult:
    case_id: str
    passed: bool
    checks: dict[str, bool]    # check name -> passed
    transcript: list[dict]     # result.messages as dicts (Message.to_dict)
    tools_called: list[str]
    cost_usd: float
    error: str | None = None

def load_cases(path: str | Path) -> list[Case]          # YAML list of mappings with the Case fields
def run_case(case: Case, model: ChatModel, *, template_db: Path, budget: Budget | None = None,
             workdir: Path | None = None) -> CaseResult
def run_suite(cases: list[Case], model_factory: Callable[[], ChatModel], *, template_db: Path,
              budget: Budget | None = None, trials: int = 1) -> list[CaseResult]
def summarize(results: list[CaseResult]) -> dict         # {"cases", "passed", "pass_rate", "cost_usd", "by_check": {name: rate}}
```
`run_case`: copy `template_db` to a fresh temp file (`shopfront.db.snapshot`), open it, build a `SupportAssistant`,
send each turn, then evaluate checks on **the database and the transcript**. A model exception → `error` set,
`passed=False`. Supported `expect` keys (each becomes one entry in `checks`; the case passes if all pass):
| key | check |
|---|---|
| `tools_called: [names]` | each name was called at least once |
| `tools_not_called: [names]` | none of these was called |
| `refund: {order_id, status}` | only refund rows **created during the case** count (compare ids before vs after): `issued` / `pending_approval` → one of them for that order has that status; `none` → none was created for that order |
| `refund_reasons_only: [reasons]` | every refund created during the case has a reason in the list |
| `escalated: true/false` | a ticket with status `escalated` was / was not created during the case |
| `order_status: {order_id, status}` | the order's status (normalized) equals `status` |
| `reply_contains_any: [strings]` | final reply contains at least one (case-insensitive) |
| `reply_not_contains: [strings]` | final reply contains none (case-insensitive) |
`run_suite`: for each trial, for each case, a fresh model from `model_factory()` (so scripted fakes restart).

## 8. `shopfront/app.py`
Replace the 501 stub in `/api/assistant/chat`: keep the request/response shape and return `{"reply": str, "session_id": str}`.
Sessions are an in-memory dict `session_id → SupportAssistant` (new uuid4 hex if none given). Model from env
`ASSISTANT_MODEL` (alias, default `"fast"`) via `agentlab.llm.registry.get_model`. Use a module-level function
`_model_factory()` so tests can monkeypatch it; it must raise if the provider has no API key (adapters create clients
lazily, so otherwise the failure would surface later as a 500). Each session gets a `Budget(limit_usd=0.25, label="web")`.
If the model can't be created, return HTTP 503 with a clear message and don't store a session. If a request's
`session_id` exists but belongs to a different `customer_id`, return 403.

## Done when
`make grade N=02` passes except tests that need the learner's `run_agent` (list them as expected red). Explain your diff.
