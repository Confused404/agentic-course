# Node 14 cheat sheet: reliability

**Retry only what can succeed**: 408/409/429/5xx/529, timeouts, dropped connections. Never 400/401/context window/
your bugs/`KeyboardInterrupt`. Status code beats error name. A 429 without `retry-after` may be a spend cap or a
free-tier daily limit: alert, don't loop.

**Backoff**: `rand() · min(cap, base · 2^(attempt-1))` (full jitter); `retry-after` wins, capped. Bound attempts
per call AND total time per run. **One retry layer**: the SDKs retry twice by default (`max_retries=0` if you own it).

**Fallback + breaker**: after retries, another model (another provider); price/trace as the model that answered.
N failed calls → open (fail fast / go to fallback) → cooldown → half-open probe.

**Durable run**: journal start · assistant · intent (before the tool) · result · approval_requested · approval · end.
Commit each before the next step. Resume = rebuild transcript + resolve the open turn.

**After a crash, for each open call** (match ids within the turn only): read → re-run · side effect without intent
→ run · side effect with intent, no result → reconcile (look first) or idempotency key; can't tell → `needs_human`
(a person records the outcome), never guess. Final answer journaled but no `end` → just write `end`.
**Requeue from the top** is safe only if every side effect is guarded.

**Durable approval**: journal the request, return, exit; decide later per call (who, why); denial = error result
the model reads; still waiting → no model call. Add deadlines + approver auth.

**Chaos**: inject faults before the provider (free) + crashes at journal/tool points; check the world (refund rows),
not the transcript. Watch **refunded but no answer** and **retried side effects**.

`python -m agentlab.reliability chaos --model fast --seeds 1`
`python -m agentlab.reliability hitl-start --model fast` → `hitl-approve RUN CALL --by you` → `hitl-resume RUN --model fast`
`python -m agentlab.reliability timeline RUN`
