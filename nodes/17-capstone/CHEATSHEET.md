# Node 17 cheat sheet: launching

**Production rules**: every failure path ends with a person (handover, never a stack trace) · identity from the
verified token on every call (a session id is not a credential), tools filtered by scopes · log outcomes, costs,
timings; no message text; ids only as keyed hashes.

**Streaming**: events = message_start · text_delta · tool_use_start · tool_input_delta (JSON fragments) · block_stop
· message_stop (stop + usage). Retry only before the first event; a cut-off stream's tool calls never run; every
wrapper must implement stream() or it's skipped.

**Gate**: policy written before the numbers; blockers vs warnings; missing ≠ passing; stale ≠ current; typos fail
loudly; re-measure on the launch configuration.

**Service order**: token → kill switch → rollout (stable hash) → assistant (prompt/tools v2, scoped) → resilient model
→ per-conversation budget (hand over) → one log event per turn.

**Monitoring**: window rates (error, handover, p95, $/conversation) with a minimum-traffic floor; tune on a drill;
runbook per alert (meaning, three checks, safe actions, owner, postmortem trigger).

**After launch**: flywheel (failed conversations → eval tasks weekly), re-gate on every model/prompt change,
blameless postmortems with the eval task that would have caught it.

`python -m agentlab.launch scorecard --evals DIR --evals-model fast --perf DIR --security DIR --security-defense D --chaos DIR --chaos-config naive` → `python -m agentlab.launch gate`
`python -m agentlab.launch drill` · `python -m agentlab.launch serve` (LAUNCH_TOKEN_SECRET, LAUNCH_DEV_TOKENS=1)
