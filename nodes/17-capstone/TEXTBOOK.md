# Node 17 TEXTBOOK: launching an agent

Launching is not the moment the code works. It's the moment you have *evidence* it works for the traffic it will
get, *limits* on what it can do when it doesn't, *eyes* on it while it runs, and a *way back*. Each section below is
one of those, assembled from what you built.

## §1 What changes in production
Your evals were scripted conversations on a seeded database. Production has: real customers (who paste order
numbers wrong, switch topics, and try things), concurrency, provider incidents, deploys, model deprecations, and
people who need answers when it fails. Three consequences shape this node:
- **Every failure path ends with a person.** A handover message and a ticket, never a stack trace or silence
  (Node 15 §7). The service treats any non-`end_turn` stop as a handover and keeps that session handed over.
- **Identity comes from the token, not the request** (Node 13). The customer id in a request body is a confused
  deputy waiting to happen; the launch service reads it from a verified token, and filters tools by its scopes.
- **What you log, you keep.** Turn events carry outcomes, costs and timings, not message text or raw customer ids:
  logs are copied, retained and read by more people than conversations are. Pseudonymise with a *keyed* hash: an
  unkeyed hash of a small id space is reversed by hashing every id. And never log anything that works as a
  credential: a session id is one unless every call also needs the token.

## §2 Streaming
Customers judge speed by the first words, not the last. Streaming sends text as the model produces it. The
mechanics, per provider: the response arrives as events (a text block grows by deltas; a tool call starts with its
name and id, then its arguments arrive as *fragments of JSON text*; the end carries the stop reason and usage).
The adapters map each vendor's events to one neutral format, and `assemble` builds the same `ModelResponse` a
non-streamed call would have returned.

The hard part is the unhappy path. A stream can be cut off by a timeout, a deploy or a dropped connection. Then:
- text already shown can't be unshown; a retry would produce a *different* answer, so retry only if nothing was
  sent yet (the `ResilientModel.stream` rule);
- a tool call from a stream that never finished must never run: even if that call's own arguments look complete,
  the *message* isn't (a later parallel call, or the rest of the answer, is missing), and "lenient" partial-JSON
  repair, which some libraries offer for showing progress, would happily turn `{"order_id": 48` into a call for
  order 48. `assemble` marks every tool call of an unfinished stream as unparsed.
Streaming also composes badly with wrappers: each layer (resilience, caching layouts, cascades) must implement
`stream()` itself, or it is silently skipped. The service streams when the model's class supports it and otherwise
answers in one piece.

## §3 Evidence: the scorecard and the gate
A launch decision should be a function of evidence, written down before you look at the numbers. The scorecard
gathers metrics from earlier nodes' runs (each with its source and date): regression and held-out pass rates and
pass^3 (Node 04), attack success rate (Node 08), cost per resolution, blended cost and p95 latency (Node 15),
refunds without an answer under chaos (Node 14). The gate applies your policy:
- **blockers and warnings**: a blocker stops the launch; a warning goes in the launch notes and on the week-one
  watch list;
- **missing is not passing**: an unmeasured metric is a blocker unless you explicitly made it optional;
- **stale is not current**: evidence older than its maximum age (or undatable) counts as missing, because the
  prompt, the model and the code have moved since;
- **typos fail loudly**: a misspelled operator must not wave a launch through.

What the gate can't do: notice that the evidence came from a different configuration than the one you're
launching. Re-run the suites on the launch configuration, and keep the run dirs' `meta.json`, which say what ran.

## §4 Limits: the launch service
The service composes the course's parts in an order that matters:
1. verify the token (audience, expiry, scopes; Node 13) → 401/403, on *every* call: the session must belong to the
   token's subject;
2. kill switch → 503 and a handover; rollout (a stable hash of customer and salt) → "not enabled yet";
3. a `SupportAssistant` with prompt and tools v2 (Node 05), tools filtered by the token's scopes;
4. the model wrapped in `ResilientModel` (Node 14);
5. a per-conversation budget (Node 15 §7): hitting it hands over;
6. one event per turn to the log (outcome, tools used, calls, cost, latency).
What it deliberately leaves out, to keep the capstone readable: durable runs for refunds (Node 14's journal),
memory (Node 06), the cascade (Node 15). Your ADR decides which of those launch day needs; adding one is a
SPEC-sized change you now know how to make.

**Rollout** is a dial, not a switch: 10% of customers by a stable hash, so the same customer always gets the same
experience and you can compare the two groups. Widen it when week-one metrics hold; change the salt to reshuffle.
**The kill switch** must not depend on the thing it switches off: a config flag the service re-reads when it
changes (no restart, no deploy, no model call), which also stops conversations already in progress.
**One resilience wrapper per process**: a circuit breaker per conversation never sees enough failures to open.

## §5 Eyes: monitoring, alerts and the drill
Monitor rates over a window, not single events: error rate (provider and agent errors), handover rate, p95
latency, cost per conversation. Alerts compare them with thresholds, but only above a minimum amount of traffic:
three conversations with one failure is not a 33% error rate, it's noise. Thresholds come from your baselines
(normal traffic) and your tolerance (how bad before someone gets paged?).

You can't tune alerts on incidents you haven't had. The drill runs simulated traffic through the real service with
fake models and a simulated clock, injecting incidents (a provider outage, a prompt regression that makes the
agent loop), and shows which alerts fire when. Tune until every incident fires within your detection target and
normal traffic never does. Then write the **runbook**: for each alert, what it means, the first three things to
check (dashboards, the turn log, a trace), the safe actions (kill switch, rollback the prompt, switch model via the
alias), who to tell, and when to write a postmortem.

## §6 After launch
- **The flywheel** (Node 04 §10): mine handed-over and low-rated conversations from the logs and traces into new
  eval tasks every week. The eval suite should grow with production, or it measures last month's product.
- **Model and price changes**: providers deprecate models and change prices (APPENDIX). Your aliases make the switch
  a config change; your evals make it a measured one. Re-run the gate on every model change.
- **Postmortems**: blameless, written, with the timeline from the turn log and traces, the detection time, and the
  eval task that would have caught it.

## Key terms
handover · confused deputy · privacy-safe logging · streaming events · partial JSON · retry-before-first-token ·
scorecard · launch gate · blocker / warning · stale evidence · rollout percentage · stable hash · kill switch ·
error/handover rate · alert threshold · minimum traffic · game day / drill · runbook · postmortem · flywheel
