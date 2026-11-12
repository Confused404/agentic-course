# Node 14: your work

Cost: tasks 2–5 and the timeline are free; the chaos run ≈ $0.05–0.15 on `fast` (`--seeds 1` for a third of
that); the HITL drill is a handful of calls.

### 1. [PREDICT] (20 min)
Read TEXTBOOK §1–§4 and `agentlab/reliability/{faults.py,journal.py}`. Predict in `LEARNING_LOG.md`, for the
default chaos run (20% provider faults per call, 10% crash chance at each crash point):
- what share of runs each of `naive`, `retry`, `requeue` and `durable` completes;
- how many "refunded but no answer" runs each produces, and how many "retried side effects" `requeue` produces;
- how much `retry`, `requeue` and `durable` add to p50 latency and to cost per run.

### 2. [AGENT-OFF] retry.py (≤ 45 min)
`is_retryable` and `backoff_delay`; grader `tests/test_retry.py`. Standard library only. Before coding, write in
your log one real error for each of the four lines of `is_retryable`'s contract, and what happens to a support
conversation if you get that line wrong in each direction.

### 3. [AGENT-OFF] recovery.py (≤ 1.25h)
`plan_recovery`; grader `tests/test_recovery.py`. It's a pure function: journal entries in, plan out.
**[READ-TRACE]** first, on paper: take the journal below (a crash right after the refund's intent) and write the
plan you'd produce: messages by role, results, pending calls with their actions, status.
```
1 start      user: "I changed my mind about order 4822. Please refund it."
2 assistant  tool_use c1 check_refund_eligibility {order_id: 4822, reason: changed_mind}
3 intent     c1
4 result     c1 {"eligible": true, "max_refundable_cents": 4899, ...}
5 assistant  tool_use c2 issue_refund {order_id: 4822, amount_cents: 4899}, tool_use c3 lookup_order {order_id: 4822}
6 intent     c2
```
Then: what if entry 6 were missing? What if there were also `7 intent c3`? What if, instead, entry 5 were a
final answer with no tool calls and the journal ended there? Why may `plan_recovery` never decide "execute" for an
intent-without-result side effect, even though it would be right most of the time?

### 4. Delegate, then review (≤ 2h)
`make new-ticket N=14` → coding agent: *"Implement nodes/14-reliability/SPEC.md. Follow AGENTS.md. retry.py and
recovery.py are mine; don't write them."*
Review for: non-retryable errors are raised at once (no fallback); `Crash` is never caught by retry code; the
fallback is priced as the fallback; every journal append happens *before* the next step and the intent before the
tool runs; reconcile with no reconciler stops with `needs_human` instead of guessing; an approval is checked per
call; a resume that's still waiting makes no model call.

### 5. Crash drills (≤ 45 min, free)
```bash
.venv/bin/python -m pytest nodes/14-reliability/tests/test_resilient_durable.py -k crash -v
```
Read `test_crash_anywhere_then_resume_refunds_exactly_once`. **[LOG]** for each parametrized crash point: which
journal entry was the last durable one, what `plan_recovery` decided, and whether the reconciler or a re-run did
the work. Then add a crash point the test doesn't cover (for example the 3rd `executed`), predict, run.

**[AGENT-OFF] (15 min)** Write a test where a crash happens after `cancel_order` ran and assert the order is
cancelled exactly once and the customer gets an answer. Then delete the `cancel_order` reconciler in your test and
assert `needs_human`; record the outcome with `resolve_manually` and resume to the end. Base your fake on
`Refunder` in `tests/conftest.py`: it decides from the transcript alone (so it behaves the same after a resume)
and gives every call a unique id (the runner refuses reused ids; `fake.ScriptedModel` restarts its ids, so a fresh
one after a resume would reuse them).

### 6. The chaos table (≤ 1.5h)
```bash
.venv/bin/python -m agentlab.reliability chaos --model fast            # free tier: add --seeds 1
.venv/bin/python -m agentlab.reliability report runs/reliability/<dir>
```
**[LOG]** the table against your predictions. For every "refunded but no answer" run and every "retried side
effect", open `results.jsonl` and explain what happened in one line. Why does `requeue` mostly work *here*, and
which Shopfront tool would make it unsafe if it lost its guard? Which column would you alert on in production?

Then rerun with `--crash-rate 0 --fault-rate 0.5`, and with `--fault-rate 0 --crash-rate 0.3` (expect even
`durable` to lose a run or two that crash more than 10 times: TEXTBOOK §7). **[LOG]** which layer fixes which
failure, and what each costs in latency (p50) and money.

**[DECIDE]** Your Node 02 adapters build SDK clients with the SDKs' default retries (2). So
`ResilientModel(get_model("fast"))` can make up to 3 × 4 = 12 attempts per call. Which layer should own retries in
this codebase? Make the change yourself (an SDK client accepts `max_retries=0`; it's your Node 02 code, not part
of the agent's SPEC) or justify keeping both, in your ADR.

### 7. An approval that outlives the process (≤ 30 min)
```bash
.venv/bin/python -m agentlab.reliability hitl-start --model fast       # prints the call waiting for approval
# close the terminal, come back later
.venv/bin/python -m agentlab.reliability hitl-approve <RUN_ID> <CALL_ID> --by you --note "checked the order"
.venv/bin/python -m agentlab.reliability hitl-resume <RUN_ID> --model fast
.venv/bin/python -m agentlab.reliability timeline <RUN_ID>
```
Do it again (`hitl-start` gives every run a fresh copy of the shop) with `--deny --note "outside the 30-day
window"`. **[LOG]** what the customer was told each time.
Order 4826 is over the shop's $200 threshold, so even an approved refund is created as `pending_approval` in the
shop: two approvals for one refund. **[DECIDE]** in your ADR: keep both gates, or which one goes?

### 8. [DECIDE] ADR 0011 (≤ 30 min)
`docs/adr/0011-reliability.md`: which errors you retry and how many times, at which layer; fallback model and
breaker settings; which tools are side effects and, for each, idempotency key, reconciler or `needs_human`; who
answers approvals, how fast, and what happens when nobody does; whether you'd keep the hand-rolled journal or
adopt a durable-execution engine (TEXTBOOK §8), and what you'd check before adopting one. Include your chaos
table and what it can't show.
