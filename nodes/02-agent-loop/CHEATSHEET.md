# Node 02 cheat sheet: the agent loop

```
loop: resp = model(system, msgs, tools) → append assistant (VERBATIM) → charge budget
      tool_use?  → one result per call, all in ONE user message, call order → continue
      pause_turn → continue        else → stop (typed)
```
**Invariants**: transcript = state (append-only) · every call gets exactly one result, next message · keep thinking
blocks · results in call order · never execute calls from a truncated (`max_tokens`) response.

**Stops**: end_turn · max_tokens · refusal · max_turns · budget · context_window_exceeded · other.
"Finished" ≠ "stopped": the caller handles the difference.

**Cost**: input tokens over n turns ≈ n·b + g·n(n+1)/2 → quadratic. Cap turns and budget in the loop.

**Adapters**: pure `to_request()` / `from_response()` + thin I/O. Canonical model = superset. Down-convert with
recorded losses: system blocks → one string; tool results → `role: tool` per call (+ images to a user message);
foreign thinking dropped; `arguments` = JSON string (parse → `parse_error`, never raise); "stop + tool_calls" → tool_use.
Drop unsupported opts *and record them*.

**Tools**: name + description + schema (model-facing) + fn (hidden). Validate args in the harness; invariants in the
service. Errors are data (`is_error`, actionable message). Identity is bound by the session, never an argument.
Sorted specs for caching. Write tools: audited, idempotent where possible, approval for risky ones.

**Evals v0**: fresh DB per case · grade state (refund rows, tickets, order status) > process (tools called) > reply
text · scripted extra user turns · 10 cases = smoke detector, not a measurement.

**Failure classes**: selection · arguments · interpretation · environment/harness.
