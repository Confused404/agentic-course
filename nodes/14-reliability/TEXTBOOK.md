# Node 14 TEXTBOOK: reliability: retries, durable runs, and humans who answer tomorrow

An agent run is a long, stateful, side-effecting program whose most important dependency (the model API) fails
several percent of the time on a bad day. Web services have dealt with each of these problems for decades. Agents
have them all at once, and they add one of their own: the program's next step is decided by a model that only knows
what's in the transcript. If the transcript is lost, so is the run.

## §1 What fails, and what it costs
| Failure | Example | What a naive loop does | What it costs |
|---|---|---|---|
| Transient provider error | 429 rate limit, 529 overloaded, 500/503, timeouts | raises; the run is gone | a customer with no answer; a retry by the user (or the queue) re-does every step |
| Permanent provider error | 400 bad request, 401, context window exceeded | raises (correct) | nothing more, unless you retry it: then latency and money for nothing |
| Provider outage | minutes to hours | every call retries, then raises | a thread pool full of sleeping retries; a minute of latency per request |
| Process crash | deploy, OOM, spot instance reclaimed, laptop lid | the run and its transcript are gone | **side effects that happened but were never reported**, or that are repeated on retry |
| Waiting for a person | approval for a large refund | blocks a worker, or is lost on restart | a stuck customer, a lost approval, a person approving the wrong thing |

The crash row is the dangerous one. A tool call has three moments: before it runs, while it runs, after it returns.
A crash before is harmless; a crash after the result is saved is harmless. A crash *between* "the refund happened"
and "we wrote down that it happened" leaves the world changed and the agent unaware. Restart the run from the top
and it will try again. Everything in §3–§4 is about that gap.

## §2 Retries, done properly
**Classify first.** A retry helps only if the next attempt can succeed. Rate limits (429), overload (529), server
errors (500, 502, 503, 504), timeouts and dropped connections usually can. A 400, a 401, a context-window error or a
bug in your own code never will: retrying burns latency and money and delays the alert. Prefer the HTTP status when
the error carries one; fall back to the error type. Never retry `KeyboardInterrupt`/`SystemExit` (in this node, a
simulated crash is a `BaseException` for the same reason: retry code must not swallow the process dying).

**Back off with jitter.** Exponential backoff (`base · 2^(attempt-1)`, capped) spaces attempts out; *full jitter*
(a uniform random delay between 0 and that value) keeps a thousand clients that failed at the same moment from
retrying at the same moment. AWS's analysis of backoff strategies found full jitter does about as well as anything
more complicated, with less work for the overloaded server (APPENDIX).

**Respect `Retry-After`.** When the provider says how long to wait (429s and 529s often do, as a header the SDKs
expose), wait that long, not your guess. Cap it anyway: a buggy header must not park a worker for an hour.

**Bound it.** A maximum number of attempts per call, and a deadline for the whole run. Retries multiply cost
silently: a run that needed 3 calls and took 9 attempts cost about the same tokens as 3 (calls rejected
with a 429 or 529 usually aren't billed; a timeout mid-generation may be) but several times the latency. Count retries and put them on the dashboard.

**Don't retry twice.** The official SDKs already retry (both the Anthropic and OpenAI Python SDKs default to 2
retries with backoff, so 3 attempts). A wrapper that makes 4 attempts around such a client turns one call into up to
12 attempts. Pick one layer: either set the SDK's `max_retries=0` and own the policy, or keep the SDK's and don't add
another.

**Fallback and circuit breaking.** If the primary keeps failing after its retries, a *fallback model* (ideally on
another provider) answers instead; price and trace that call as the fallback, or your cost numbers lie. If a
provider fails call after call, a *circuit breaker* stops trying it for a cooldown period: calls fail fast (or go
straight to the fallback) instead of each waiting through a full retry sequence. After the cooldown, one call is let
through to probe (half-open). Gateways such as OpenRouter offer server-side fallback (a list of models tried in
order); it's the same idea one hop away, and it doesn't replace your own classification (APPENDIX).

**What retries can't fix:** the crash. A retry wrapper lives in the process that died.

## §3 Durable runs: write it down before you take the next step
A *durable* run journals every step to storage that survives the process, so a new process can rebuild the run and
continue. This node's journal (`journal.py`, an append-only SQLite table) records:

| kind | written | contains |
|---|---|---|
| `start` | once | system prompt, initial messages, config |
| `assistant` | after each model call | the full assistant message (text and tool calls) |
| `intent` | **before** a tool runs | call id, tool, args |
| `result` | after a tool returns | call id, content, is_error (and `reconciled` if recovered) |
| `approval_requested` / `approval` | when the run pauses / when a person decides | call id, who, note |
| `end` | once | stop reason, final text |

Recovery is a pure function from the journal to a plan (`plan_recovery`, YOU_DO task 3): rebuild the transcript from
`start` and the completed turns, find the last turn's open tool calls, and decide for each: run it, reconcile it,
or wait for a person. Then the runner continues the loop from there. Because the model only knows the transcript,
a rebuilt transcript is a rebuilt agent: the model can't tell the difference.

This is the same idea as a database's write-ahead log, and as what durable-execution tools keep for you. They come
in two kinds. *Replay* engines (Temporal, DBOS, Restate) record each step's result and, after a crash, re-run your
code from the top, feeding it the recorded results instead of repeating the steps; that requires deterministic
code. *Checkpointing* frameworks (LangGraph's checkpointers) save a snapshot of the state after each step and, on
resume, restart the interrupted step from the last snapshot. This node records the *transcript*, which is enough
because the agent's state is the transcript. Read §8 before deciding to hand-roll this in production.

**Commit before acting.** Each journal append is committed before the next step starts. Batching appends "for
speed" re-opens the gap from §1: the refund happened, its intent was in an uncommitted batch.

**Model calls are re-done, not reconciled.** If the process dies after the model answered but before the
`assistant` entry was written, the resumed run asks the model again and may get a different answer. That's fine:
nothing happened in the world yet. It costs one call. The reverse case matters more: if the *final* answer was
journaled and the crash came before `end`, the run is finished; asking the model again would answer twice (or send
a transcript ending in an assistant message, which some APIs reject). That's why the journal keeps each response's
`stop_reason`: it also stops a resume from running tool calls that were cut off by `max_tokens`.

**Ids must be unique.** Recovery matches results to calls by call id, and only within the turn. Providers never
reuse ids; a test fake that does would make one call's result look like another's, so the runner refuses
duplicates.

## §4 Side effects: at most once, at least once, or reconciled
For a read (look up an order), running it twice is harmless: on resume, an intent without a result is just run
again. For a side effect, there are three honest options:

1. **Idempotency keys.** The tool accepts a key (e.g. the call id) and the service refuses to do the same keyed
   action twice, returning the original result instead. Payment APIs work like this (APPENDIX). This is the best
   option, and it needs the *service* to support it.
2. **Reconcile.** Before re-running, *look*: does a refund for this order already exist? If yes, record it as the
   result (marked `reconciled`) and move on; if no, it's safe to run. This needs a question you can ask the world
   whose answer is unambiguous. "Refund for order 4822 exists" is; "an email with this subject was sent" often isn't.
3. **Stop and ask a person.** If you can't tell whether it happened, don't guess. Either guess is wrong sometimes
   (a double refund or a missing one). The runner stops with `needs_human`.

**What most teams do instead: requeue.** Put the job back on the queue and run it again from the top. That's
safe only if every side effect is guarded. Shopfront happens to have guards: `check_refund_eligibility` reports an
existing refund, and `issue_refund` refuses a second one for the same order ("already exists"). Those are business
rules, not idempotency: they turn a would-be double refund into an *error the model sees*, and a model that sees
"refund failed" may tell the customer exactly that, after the money moved. The chaos lab's `requeue` configuration
shows it; the table counts these as "retried side effects". Many real tools (send an email, post a message,
charge a card without a key) have no such guard; there, a requeue after a crash is a duplicate.

**Crash points.** The runner has two places a crash matters: right after a journal append, and right after a tool
ran but before its result was journaled. The tests crash at each one (`hook("journaled")`, `hook("executed")`)
and check that the resumed run ends with exactly one refund. Writing those tests is cheap; finding out in
production isn't.

## §5 Humans in the loop, durably
In Node 03 an approval was a blocking prompt: the process waited at `input()`. That doesn't survive anything. A
durable approval is just another journal state:

1. The runner reaches a call that needs approval, journals `approval_requested`, and **returns**
   (`awaiting_approval`). The process can exit.
2. Later, anyone with access records the decision (`approval`: approved or denied, by whom, why), from any process.
3. Resume: approved calls run; a denial becomes an error result the model reads ("Denied by maria: fraud check"),
   so it can tell the customer honestly instead of crashing.

Things to get right: approvals are keyed to a specific call (not "approve the run"), each can be decided once, the
approver sees the exact arguments that will run, and a resume with nothing decided goes straight back to waiting
without a model call. In a real system you'd add a deadline (an approval nobody answers in 24 hours escalates or
expires) and authentication of the approver (Node 13).

The shop has its own approval queue: refunds over $200 are created as `pending_approval`. That's a *domain*
workflow (the money waits for the finance team). The durable approval is the *agent's* gate: the run itself waits,
and when it resumes it can tell the customer what happened. You'll see both in YOU_DO task 6; decide in your ADR
whether you'd keep both.

## §6 Seeing what happened
The journal doubles as the run's history: `timeline` prints it, with time offsets, for support engineers who need
to answer "what did the agent do for this customer, and when?". Traces (Node 01) answer a different question:
where did the time and money go, across many runs. Keep both: the journal is the source of truth for recovery,
the traces are for dashboards and alerts (retry rate, fallback rate, breaker opens, runs waiting for approval and
for how long, `needs_human` count). The OpenTelemetry GenAI conventions name the span attributes; check their
stability before you build dashboards on them (APPENDIX).

## §7 Measuring reliability with chaos
You can't wait for the next outage to find out. The chaos lab (`chaos.py`) injects faults deterministically:
`FaultyModel` raises provider errors at a chosen rate *before* the call reaches the provider (so injected faults are
free), and a crasher kills the "process" at random crash points. It runs five support scenarios under four
configurations:

- `naive`: Node 02's loop, no protection;
- `retry`: the loop with `ResilientModel`;
- `requeue`: `retry`, plus a lost job is run again from the top (up to 3 times), like a job queue;
- `durable`: the durable runner, with retries, resumed after each crash like a restarted worker (up to 10 times).

Then it checks the world, not the transcript: does the customer have an answer, and does the database hold exactly
the expected refunds? The column that matters most is **refunded but no answer**: money moved, the customer was
never told. That's the incident from the ticket.

The crash points differ by design: `naive`/`retry`/`requeue` can only crash right after a tool ran, while
`durable` can crash after every journal append too (about three times as many points). So at the same crash rate
`durable` sees more crashes; compare outcomes, not crash counts. At high crash rates (0.3 and up) even `durable`
loses runs that crash more than 10 times; that's the resume limit working, not a bug.

What the table can't show: a real outage is correlated (every run fails at once, for an hour), real crashes
cluster around deploys, and five scenarios are a smoke test, not a distribution. Seeds make it reproducible, not
representative. Use it to catch regressions and to compare designs; use incident reviews for the rest.

## §8 Build or buy
This node hand-rolls a journal so you can see every moving part. In production, prefer a durable-execution engine
or your framework's persistence layer: they handle concurrency (two workers resuming the same run), retention,
versioning (a run started under prompt v3 resuming under v4), timers for approval deadlines, and visibility. What
they don't do for you: decide which tools are side effects, provide idempotency keys or reconcilers, or classify
errors. Those decisions are yours either way, and they're what this node's AGENT-OFF tasks are about.

Two warnings when adopting one. First, replay-based engines require deterministic workflow code: model and tool
calls must be activities/steps, never called directly from workflow code. Second, check what the integration
actually persists: some framework integrations checkpoint between *steps* (a whole agent turn), not between tool
calls, which re-opens the gap from §1 inside a turn.

## Key terms
transient vs permanent error · full jitter · Retry-After · retry budget · double retry · fallback model · circuit
breaker (open, half-open) · durable execution · journal / event history · write-ahead · intent · reconcile ·
idempotency key · at-most-once / at-least-once · `needs_human` · durable approval · chaos testing · correlated
failure
