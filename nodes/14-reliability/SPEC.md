# SPEC: Node 14: a resilient model wrapper, durable agent runs, and a chaos lab

**For the coding agent.** Read `AGENTS.md`. Background: TEXTBOOK §2–§7.
**AGENT-OFF (the learner's; never write or edit them):** `agentlab/reliability/retry.py` (`is_retryable`,
`backoff_delay`) and `agentlab/reliability/recovery.py::plan_recovery`. Call them through their modules
(`retry_module.is_retryable`, `recovery_module.plan_recovery`) so tests can substitute them.
**GIVEN (don't rewrite):** `agentlab/reliability/faults.py` (`ProviderError` and subclasses, `Crash`, `FAULTS`,
`FaultyModel`), `journal.py` (`Journal`, `KINDS`), `recovery.py`'s `PendingCall`/`RecoveryPlan`. Reuse Node 02's
`run_agent`/`LoopConfig`, Node 05's `make_support_tools(..., variant="v2")` and `get_prompt("v2")`, Node 09's
`Budget`, Node 01's `tracing`.

## Files
```
create  agentlab/reliability/resilient.py   (1)
create  agentlab/reliability/durable.py     (2)
create  agentlab/reliability/chaos.py       (3)
create  agentlab/reliability/__main__.py    (4)
```
Nothing outside `agentlab/reliability/` changes (YOU_DO task 6 may have the learner change the Node 02 adapters'
SDK retries; that's theirs, not yours). `make grade-upto N=14` must stay green for 00–13.

## 1. `resilient.py`
```python
def retry_after_s(err) -> float | None   # err.retry_after if set, else float(err.response.headers["retry-after"])
                                         # (the SDKs' errors carry the HTTP response); HTTP-date, NaN, negative,
                                         # missing or unreadable -> None
class CircuitOpen(Exception)
@dataclass class ResilientModel:        # a ChatModel: .provider, .model, .complete(**kw)
    inner; max_attempts=4 (tries per call incl. the first); base=0.5; cap=20.0; fallback=None;
    breaker_threshold=5 (consecutive failed CALLS, i.e. after their retries); breaker_cooldown_s=30.0;
    sleep=time.sleep; clock=time.monotonic; events: list[str]; retries: int (total retries made)
    # provider/model start as inner's; max_attempts < 1 -> ValueError
    def complete(**kw):
        # breaker open (opened, cooldown not passed)? -> fallback.complete(**kw) if fallback else raise CircuitOpen.
        #   Cooldown passed -> close it ("breaker half-open" event) and let the call through.
        # for attempt 1..max_attempts: inner.complete(**kw); success -> reset failed-call count, return.
        #   Exception not retryable (retry_module.is_retryable) -> re-raise at once (no fallback: a bad request is
        #   bad on the fallback too). Retryable and attempts left -> sleep(retry_module.backoff_delay(attempt,
        #   base, cap, retry_after=retry_after_s(e))), retries += 1, event "retry N after <Type>…".
        # all attempts failed -> failed calls += 1; reaching breaker_threshold opens the breaker ("breaker opened");
        #   then fallback (event "fallback after <Type>") or re-raise the last error.
        # BaseExceptions that aren't Exceptions (Crash, KeyboardInterrupt) are never caught.
        # Whenever a model answers, set self.provider/self.model to THAT model's (the loop prices and traces with
        # them after complete() returns): the fallback must be priced as the fallback.
```

## 2. `durable.py`
```python
Reconciler = Callable[[dict], dict | None]   # tool args -> the result if the effect already happened, else None
Hook = Callable[[str, dict], None]           # (point, info); points: "journaled" (info = the entry, after it's
                                             # committed), "executed" (info = {call_id, tool}, after the tool ran,
                                             # BEFORE its result is journaled). Tests raise Crash from it.
STOPS = {"end_turn"|"stop_sequence" -> "end_turn", "max_tokens", "refusal", "context_window_exceeded"}  # Node 02's
@dataclass class DurableResult: run_id; status ("done"|"awaiting_approval"|"needs_human"); stop=""; final_text="";
                                turns=0; cost_usd=0.0; note=""
class DurableAgent:
    def __init__(journal, tools: ToolRegistry, *, side_effect_tools=None (-> names of tools with side_effects=True),
                 approval_tools=frozenset(), reconcilers=None, hook=None)
    def start(run_id, model, system, messages, *, budget=None, max_turns=10, max_tokens=2048) -> DurableResult
        # existing run_id -> ValueError. Journal "start" {system, messages (to_dict), config {max_turns,
        # max_tokens}}, then resume().
    def resume(run_id, model, *, budget=None) -> DurableResult
        # plan = recovery_module.plan_recovery(journal.entries(run_id), side_effect_tools);
        # "done" -> the end entry's stop/final_text (no model call); "done" with NO end entry (the answer was
        # journaled, then a crash) -> journal "end" from the last assistant entry (stop via STOPS, its text) and
        # return it, still without a model call. "awaiting_approval" -> that status, note = the waiting call ids
        # (no model call). Else drive the loop from the plan.
    def approve(run_id, call_id, approved: bool, by: str, note="")
        # no approval_requested for call_id -> KeyError; already decided -> ValueError; else journal "approval".
    def pending_approvals(run_id) -> list[dict]       # approval_requested entries not yet decided
    def resolve_manually(run_id, call_id, content, by)  # for `needs_human`: call_id not among the plan's pending
        # calls -> KeyError; else journal "result" {call_id, content, is_error=False, reconciled=True, resolved_by=by}
```
The loop (same shape as Node 02's `run_agent`, inside `tracing.agent_span("durable")`, model calls in
`tracing.chat_span`, tools in `tracing.tool_span`; turns counted from the journal's assistant entries; max_turns
and max_tokens from the plan's config; `budget.check()` before and `budget.charge()` after each model call):
1. Resolve the open turn's pending calls **in order**, then append one user message with a result per tool call
   of that turn, in call order (known results from the plan plus the new ones). Resolving one call:
   - its ToolUseBlock has `parse_error` -> journal an error `result` ("Invalid tool arguments (...)") without
     running it (Node 02's rule: unparsed arguments would run as `{}`); no intent.
   - `reconcile`: no reconciler for the tool -> stop with `needs_human` (note = call id). Reconciler returns a
     dict -> journal it as the result (JSON, `reconciled=True`), done. Returns None -> treat as `execute`.
   - tool in `approval_tools` and no approval with approved=True for this call -> journal `approval_requested`
     {call_id, tool, args}, stop with `awaiting_approval`.
   - execute: journal `intent` {call_id, tool, args} -> `tools.execute` -> `hook("executed", …)` -> journal
     `result` {call_id, content, is_error}.
2. Stop at max_turns. Else call the model. Tool calls (only when stop_reason is "tool_use") whose ids repeat
   within the response or any earlier call of the run -> ValueError (recovery matches by id). Journal `assistant`
   {message, stop_reason} **before** `budget.charge()` (if charging raises, the paid answer is kept and a resume
   doesn't pay for it again). `pause_turn` without calls -> call again (no user message). No tool calls -> journal
   `end` {stop (STOPS, else "other"), final_text} and return `done`. Else the calls become the new pending list
   (`execute`), go to 1.
Every `journal.append` is followed by `hook("journaled", entry)`.
```python
def run_until_done(agent, run_id, model, *, budget=None, max_resumes=10, sleep=time.sleep) -> (DurableResult, resumes)
    # resume; on Crash -> resume again; on an Exception that is retryable (retry_module.is_retryable) or CircuitOpen
    # -> sleep(backoff_delay(resumes + 1, base=1.0, cap=30.0)) and resume; any other exception (a bug, a bad
    # request, BudgetExceeded) -> raise at once. After max_resumes, raise the last error with `.resumes` set on it.
def timeline(entries) -> str     # one line per entry: seq, +seconds since start, kind, a short detail (user text,
                                 # assistant text and tool calls, tool+args, "ERROR"/"[reconciled]" + content,
                                 # "APPROVED|DENIED by X: note", stop + final text)
```

## 3. `chaos.py`
```python
CONFIGS = ("naive", "retry", "requeue", "durable"); MAX_REQUEUES = 3; MAX_RESUMES = 10
@dataclass(frozen=True) class Scenario: id; customer_id; message; refund_order (exactly one refund expected there;
                                                                              None: no refund by this run at all)
SCENARIOS = damaged (9001, 4821), changed_mind (9001, 4822), plus (9002, 4823), where (9003, None), big (9006, 4826)
def shop_reconcilers(conn, customer_id=None) -> {"issue_refund", "cancel_order", "escalate_to_human"}
    # each returns what the tool would have returned if the effect happened, else None; scoped to customer_id's
    # orders/tickets when given. refund: latest refunds row for the order -> {refund_id, status, amount_cents,
    # note "already exists (recovered…)"}; cancel: order status (stripped, lowercased) "cancelled" -> {order_id,
    # status, note} like cancel_order's result; escalate: a chat ticket whose BODY is the summary
    # (services.escalate_to_human stores it there) -> {ticket_id, status "escalated", note}
@dataclass class ChaosResult: scenario; config; seed; completed (end_turn and a non-empty answer); refund_ok;
    refunds; duplicate_attempts (refund results saying "already exists" that were NOT reconciled); injected: list;
    crashes; resumes; retries; cost_usd; latency_s; error=None; final_text=""
class Crasher(rate, seed): .maybe() raises Crash if rng.random() < rate, rng = random.Random(seed); .crashes
def run_one(scenario, config, model, conn, *, fault_rate, crash_rate, seed, budget=None, sleep=time.sleep)
    # FaultyModel(model, rate=fault_rate, seed=seed); naive uses it directly; retry/durable wrap it in
    # ResilientModel(…, sleep=sleep, cap=4.0). Tools: make_support_tools(conn, customer, actor="agent:chaos",
    # variant="v2"); system: get_prompt("v2") with {today}.
    # naive/retry/requeue: run_agent (max_turns 8) with tools wrapped so crasher.maybe() runs right after each tool.
    #   requeue: a lost attempt (Crash/Exception) runs again FROM THE TOP with a fresh transcript, like a job queue,
    #   up to MAX_REQUEUES times (resumes = reruns). r.stop == "budget" -> raise BudgetExceeded (run_agent reports
    #   it instead of raising; the lab must stop). duplicate_attempts = issue_refund results saying "already exists".
    # durable: a Journal in a temp dir; DurableAgent(reconcilers=shop_reconcilers(conn, customer), hook =
    #   crasher.maybe at "journaled" (not the start entry) and "executed"); start; on Crash/Exception (not
    #   BudgetExceeded) -> run_until_done(max_resumes=MAX_RESUMES - 1, sleep=sleep); resumes counts every resume,
    #   including those of a run that was lost in the end (the error's `.resumes`).
    # Any Crash/Exception left -> error = "<Type>: msg" (the run is lost). BudgetExceeded propagates.
    # Afterwards count refunds in the DB (the scenario's order, or actor 'agent:chaos' when refund_order is None).
def run_chaos(model_factory, conn_factory, *, configs=CONFIGS, scenarios=SCENARIOS, seeds=(0,1,2), fault_rate=0.2,
              crash_rate=0.1, budget=None, out=None, sleep=time.sleep) -> list[ChaosResult]
    # a fresh conn per run (closed after); out -> results.jsonl (truncated at start, one line per run)
def summarize(results) -> {config: {n, completed, refund_ok, silent (refunds > 0 and not completed),
                                    duplicate_attempts, faults, crashes, resumes, retries, cost, p50_s}}
def render(results) -> str    # markdown table, one row per config; columns include "customer got an answer",
                              # "refunds correct", "refunded but no answer", "retried side effects"
```

## 4. `__main__.py`
```
python -m agentlab.reliability chaos --model ALIAS [--configs naive,retry,requeue,durable] [--seeds 3] [--fault-rate 0.2]
                                     [--crash-rate 0.1] [--budget 0.5]
python -m agentlab.reliability report RUN_DIR
python -m agentlab.reliability hitl-start --model ALIAS
python -m agentlab.reliability hitl-approve RUN_ID CALL_ID --by NAME [--deny] [--note TEXT]
python -m agentlab.reliability hitl-resume RUN_ID --model ALIAS
python -m agentlab.reliability hitl-resolve RUN_ID CALL_ID --by NAME --result TEXT
python -m agentlab.reliability timeline RUN_ID [--journal PATH]
```
- `chaos`: validate configs (unknown -> ValueError), seeds >= 1, rates in [0, 1] and the alias (`config.resolve`)
  **before** creating anything;
  out = `new_run_dir(RUNS / "reliability")`; each run gets a fresh snapshot of a seeded template DB built once
  in the run dir; seeds 0..N-1; write `meta.json`; print `render`.
- `report`: render a run dir's `results.jsonl`.
- HITL commands share `RUNS/reliability/hitl/journal.db` so each can run in a **new process**; each run gets its
  own shop: `hitl-start` snapshots a template (seeded once into `hitl/template/`) to `hitl/<RUN_ID>/shop.db`, and
  the other commands open that run's DB (missing -> a clear error). Agent: customer 9006, `actor="agent:hitl"`,
  `approval_tools={"issue_refund"}`, `shop_reconcilers(conn, 9006)`. `hitl-start` starts run
  `refund-4826-<YYYYmmdd-HHMMSS>` with "Order 4826 isn't what I wanted. Please refund it in full." (max_turns 8)
  and prints the status, each waiting call with the exact `hitl-approve` command, and for `needs_human` the
  `hitl-resolve` command. Models are wrapped in `ResilientModel`. `hitl-approve`/`hitl-resolve` need no model.
- `timeline`: default journal = the HITL one (none yet -> say so, exit 1); unknown run -> print the runs that exist.

## Tests
`nodes/14-reliability/tests/`: graders for your two AGENT-OFF files (`test_retry.py`, `test_recovery.py`), and
offline tests of the wrapper, the durable runner (a crash at each crash point, then a resume in a fresh
`DurableAgent` must leave exactly one refund), approvals across instances, and the chaos lab with a scripted model.
Test fakes must give every tool call a run-unique id (see `Refunder` in `tests/conftest.py`).
The fixtures `needs_retry`/`needs_recovery` skip the dependent tests until the AGENT-OFF code exists.
