# SPEC: Node 17: streaming, the launch service, scorecard, gate CLI, monitoring and the HTTP API

**For the coding agent.** Read `AGENTS.md`. Background: TEXTBOOK §2–§5.
**AGENT-OFF (the learner's; never write or edit them):** `agentlab/launch/stream.py::assemble` and
`agentlab/launch/gate.py::launch_decision`. Call them through their modules (`stream_module.assemble`,
`gate_module.launch_decision`).
**GIVEN (don't rewrite):** the event format in `stream.py`'s docstring, `Decision`, `config/launch.toml`,
`nodes/17-capstone/launch_policy.toml`. Reuse: Node 02 adapters (`to_anthropic_request`, `to_openai_request`, their
lazily created `client`), Node 04 `summarize`/`load_trials`/`error_kind`, Node 05 prompts/tools v2, Node 08
`security_summary`, Node 13 `verify_token`/`TokenError`/`scoped_registry`, Node 14 `ResilientModel`,
`chaos.summarize`/`ChaosResult`, `FaultyModel`, Node 15 `perf.bench.summarize`, `economics.percentile`.

## Files
```
create  agentlab/launch/streaming.py      (1)
edit    agentlab/llm/anthropic_adapter.py (1)  add stream()
edit    agentlab/llm/openai_compat.py     (1)  add stream()
edit    agentlab/reliability/resilient.py (1)  add stream()
create  agentlab/launch/service.py        (2)
create  agentlab/launch/scorecard.py      (3)
create  agentlab/launch/monitor.py        (4)
create  agentlab/launch/server.py         (5)
create  agentlab/launch/__main__.py       (6)
```
`make grade-upto N=17` must stay green for 00–16.

## 1. Streaming
```python
def anthropic_events(raw) -> Iterator[dict]   # raw Anthropic stream events (objects with model_dump() or dicts):
    # message_start -> {"type":"message_start", id, model} (remember input/cache usage); content_block_start
    # tool_use -> tool_use_start {index, id, name}; text with non-empty text -> text_delta; content_block_delta
    # text_delta -> text_delta, input_json_delta -> tool_input_delta {index, partial_json}; content_block_stop ->
    # block_stop; message_delta -> remember stop_reason and output_tokens; message_stop -> {"type":"message_stop",
    # stop_reason (end_turn/tool_use/max_tokens/stop_sequence/pause_turn/refusal, else "other"), usage {input_tokens,
    # cache_read_tokens, cache_write_tokens, output_tokens}}. Anything else ignored.
def openai_events(chunks) -> Iterator[dict]   # first chunk -> message_start {id, model}; delta.content ->
    # text_delta index 0; delta.tool_calls[k]: first sight -> tool_use_start (block index = 1 + order of first
    # sight; id or "call_<k>"), arguments -> tool_input_delta; finish_reason remembered (stop->end_turn,
    # tool_calls/function_call->tool_use, length->max_tokens, content_filter->refusal, else other; ANY tool call seen
    # -> "tool_use" whatever finish_reason says); fallback tool ids must be unique across calls (e.g. a random
    # prefix per stream: "call_<rand>_<k>"); a chunk with usage
    # -> usage {input_tokens = prompt - cached, cache_read_tokens = cached, output_tokens, cost_usd = usage.cost}.
    # After the last chunk: message_stop ONLY if a finish_reason was seen (else the stream was cut off).
def run_stream(mapped, *, provider, model) -> Iterator[dict]  # yields the events, then {"type":"response",
    # "response": stream_module.assemble(all events, provider=..., model=...)}
def stream_or_complete(model, **kw)  # if type(model) defines a callable stream (class attribute: a wrapper that
    # merely forwards attributes doesn't count) -> yield from model.stream(**kw); else complete() and yield
    # message_start, one text_delta (if any text), and {"type":"response", ...}
```
Adapters: `stream(*, system, messages, tools=None, max_tokens=1024, **opts)` builds the same request as
`complete()` (and sets `last_dropped_opts`), calls the SDK with `stream=True` (OpenAI-compatible: also
`stream_options={"include_usage": True}`), and `yield from run_stream(<mapper>(raw), provider=..., model=self.model)`.
`ResilientModel.stream(**kw)`: if the inner model's class has no stream -> yield one `response` event from
`complete()`; breaker open -> fallback via `stream_or_complete` or `CircuitOpen`; else attempts like `complete()`,
but once a text_delta / tool_use_start / tool_input_delta has been yielded (something the customer could see;
message_start doesn't count), an exception is re-raised at once (never retried) and counts as a failed call for the
breaker; a retryable failure before
any event backs off (`retry_after_s`, event "stream retry N after <Type>...") and retries; exhausted -> breaker
accounting as in complete(), then the fallback via `stream_or_complete`, else raise.

## 2. `service.py`
```python
CONFIG = ROOT / "config/launch.toml"
@dataclass class LaunchConfig: model="fast"; prompt="v2"; tools="v2"; max_turns=8; budget_per_conversation_usd=0.05;
    handover_message; rollout_percent=10.0; rollout_salt="launch"; kill_switch=False;
    audience="shopfront-assistant"; required_scopes=frozenset({"orders:read"}); max_message_chars=4000
def load_config(path=CONFIG) -> LaunchConfig     # [assistant], [rollout] (percent, salt, kill_switch), [auth];
    # percent outside [0, 100], max_turns < 1 or budget <= 0 -> ValueError
def in_rollout(customer_id, percent, salt) -> bool   # int(sha256(f"{salt}:{customer_id}").hexdigest()[:8], 16)
    # % 10_000 < percent * 100
class AccessDenied(Exception): status; reason
@dataclass class Session: id; customer_id; subject (the token's sub); assistant; budget; model; conn=None; turns=0;
                         handed_over=False; expires_at=0
@dataclass class LaunchService: cfg; secret; model_factory; conn_factory; log_path=None; clock=time.time;
                                config_path=None; sessions
    def refresh_config()     # config_path's mtime changed -> cfg = load_config(config_path) (the kill switch and
                             # rollout take effect without a restart); called at open_session and stream
    def open_session(token) -> Session      # first: refresh_config; drop and close expired sessions
        # tokens_module.verify_token(token, secret, audience=cfg.audience, required_scopes=cfg.required_scopes,
        # now=int(clock())): TokenError insufficient_scope -> AccessDenied(403), other TokenError -> 401; no
        # customer_id -> 403; kill switch -> 503 with the handover message as the reason; not in rollout -> 404. Budget(cfg.budget_per_conversation_usd);
        # SupportAssistant(model_factory(), conn_factory(), customer, budget, max_turns, prompt, tools); then
        # assistant.tools = scoped_registry(assistant.tools, principal). Session expires with the token.
    def stream(session_id, text, token) -> Iterator[dict]   # the token is verified on EVERY call (a session id is
        # not a credential): bad token -> 401/403; unknown session, or a token for another sub/customer -> 404;
        # expired -> 401 (forget the session, close its connection). Then the turn (also `_turn(session, text)`, for
        # callers that already authorised): text longer than max_message_chars -> a polite "too long" done event
        # (stop "too_long", no handover). Kill switch or already handed over
        # -> one {"type":"done", reply=handover_message, stop "handover", handover True}. Else a turn loop on the
        # assistant's working messages + the user message (append the user message to the transcript FIRST): per
        # model call (at most max_turns): budget.check(); stream_or_complete(model, system, messages, tools specs,
        # max_tokens=1024) in a chat_span, yielding {"type":"delta","text"} per text_delta; charge the budget (if the
        # charge crosses the cap on a complete end_turn answer the customer has already seen, the answer stands and
        # the session hands over from the next turn; otherwise BudgetExceeded as below);
        # tool calls -> {"type":"tool","name"} per call, then execute (parse_error -> error result, not executed);
        # no tool calls -> stop (end_turn/stop_sequence -> "end_turn", else the stop reason). BudgetExceeded ->
        # stop "budget"; any other exception -> stop "error" with error_kind(e). stop != end_turn or no text ->
        # handover (reply = handover_message, session handed over for good). Update the assistant's messages and
        # transcript; log one event; yield {"type":"done", reply, stop, handover}.
    def chat(session_id, text, token) -> dict   # the "done" event of stream()
    # log event (JSONL): ts, session and customer as KEYED pseudonyms (HMAC-SHA256 with the secret of
    # "session:<id>" / "customer:<id>", 16 hex), turn, stop, handover, budget_hit, error_kind, calls, tools (names
    # called this turn), cost_usd, latency_s (measured with `clock`). NO message text, no raw or replayable ids;
    # the trace span gets the same pseudonyms.
```

## 3. `scorecard.py`
`measured_at(run_dir)`: meta.json "started" if it parses with a timezone, else the mtime (UTC ISO) of meta.json, or
of trials.jsonl/results.jsonl, or the dir. `build_scorecard(*, evals_dir, evals_model, perf_dir, perf_config,
security_dir, security_defense, chaos_dir, chaos_config="durable", human_cost_usd=4.0)` -> {metric: {value, measured_at,
source}}. A summary with several entries and no name given, or a name not in it -> ValueError. Metrics:
evals: `regression_pass_rate` (Node 04 summarize pass_rate), `pass_hat_3` (pass_hat_k), `heldout_pass_rate`
(trials with split "heldout", None if none); perf: `cost_per_resolution` (inf -> None), `blended_cost`,
`p95_latency_s`; security: `attack_success_rate` (asr), `benign_utility`; chaos: `chaos_completed`,
`refunded_without_answer` (silent). `regression_pass_rate` is computed over the evals run's NON-held-out trials
(of the chosen model); held-out tasks only feed `heldout_pass_rate`.

## 4. `monitor.py`
`window_metrics(events, *, now, window_s)` over events with now - window_s < ts <= now: conversations (distinct
sessions), turns, error_rate (error_kind set), handover_rate, p95_latency_s (economics.percentile), cost_per_conversation
(None when empty). `firing(metrics, cfg)`: [] below cfg min_conversations (default 5); else "<metric> <value> >
<limit>" for each of error_rate, handover_rate, p95_latency_s, cost_per_conversation above cfg "<metric>_max".
`Phase(name, minutes, model factory)`; `default_phases()`: normal (a fake that answers), provider outage
(`ResilientModel(FaultyModel(answer, rate=0.9, random_faults=("529","503")), max_attempts=2, no sleep)`), recovered,
prompt regression (a fake that calls `search_help_center` forever), fixed. The outage's FaultyModel gets a new seed
per conversation (a counter), so its rate is a rate. `run_drill(make_service(model_factory,
clock), token_for, cfg, *, phases=None, conversations_per_minute=2, check_every_min=5)`: simulated minutes, one
"Where is my order?" per conversation, window metrics + firing every check -> `DrillResult(timeline, events)`;
`render_drill(result)` -> markdown (minute, phase, conversations, error rate, handover, p95, $/conv, alerts).

## 5. `server.py`
`create_app(service=None) -> FastAPI` (default: `load_config()`, secret from `LAUNCH_TOKEN_SECRET` (>= 32 bytes,
else RuntimeError), `ResilientModel(get_model(cfg.model))`, `db.connect`, log `RUNS/launch/events.jsonl`).
The default service shares ONE `ResilientModel` across sessions (the breaker is process state) and re-reads
`config/launch.toml` on change. `POST /api/v2/session` (Authorization: Bearer; missing -> 401; AccessDenied -> its
status), `POST /api/v2/chat` {session_id, message} + the same bearer token, `POST /api/v2/stream` (bearer token;
check the session first so errors are status codes; then text/event-stream with `Cache-Control: no-cache` and
`X-Accel-Buffering: no`, one `data: <json>\n\n` per event of `_turn`), `GET /api/v2/health` {ok, kill_switch,
rollout_percent, sessions}; `POST /api/v2/dev/token` {customer_id} only when `LAUNCH_DEV_TOKENS=1` (all four
scopes, the service's audience and clock).

## 6. `__main__.py`
`scorecard` (flags --evals/--evals-model/--perf/--perf-config/--security/--security-defense/--chaos/--chaos-config;
at least one run dir, each must exist; writes JSON, default `RUNS/launch/scorecard.json`, and prints
it), `gate` (scorecard + policy `rules`; prints GO/NO-GO and every blocker, warning and pass; exit 0 = go, 1 =
no-go), `drill` (the policy's `[alerts]`; `load_config()` with rollout 100% and no kill switch; a temp seeded shop;
prints `render_drill`), `serve`
(uvicorn, `--port 8001`).

## Tests
`nodes/17-capstone/tests/`: graders for `assemble` and `launch_decision`, recorded Anthropic/OpenAI streams through
the mappers and the adapters (fake SDK clients), retry-before-first-event, the service's access rules, streaming
turn, handovers and log privacy, the HTTP API with FastAPI's TestClient, the scorecard, window metrics, and the
drill (alerts fire in incidents, never in normal traffic).
