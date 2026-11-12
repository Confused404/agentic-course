# Node 05 cheat sheet: prompt and tool design

**Everything in context is a prompt**: system prompt, tool names/descriptions/schemas, tool results, error messages.

**Loop**: failure (trace) → hypothesis → ONE change → paired experiment (same tasks, interleaved) → log → keep/revert.
Full-suite regression check before accepting. Held-out once at the end.

**System prompt**: role/context · priorities · policies *with reasons* · procedures for frequent error-prone paths ·
boundaries + escalation · style. Say what to do, not only what not to do. Don't shout. Resolve conflicts explicitly.
Per-request content (date, tier, retrieved text) at the END (prefix cache). Delimit untrusted text; long docs
before the question. Reasoning models: set effort, don't script the thinking.

**Tools (ACI)**: distinct verb names · descriptions = what / when (and when not) / returns / gotchas · enums for
categories · units in names (`amount_cents`) · per-param descriptions with examples · `additionalProperties: false` ·
return derived facts (`days_since_delivery`, `max_refundable_cents`, dollars) · consistent error shape.
Strict mode guarantees shape, not sense. >10–20 tools: consolidate or load dynamically (tool search).
Renaming tools = migrating every grader that references them.

**Errors**: problem in the model's terms + facts + **next steps** + valid options; no stack traces or internals.

**Few-shot**: strongest signal, gets copied; diverse or none; micro-examples inside parameter descriptions.

**Power**: a 23-task suite sees ~15-pt effects. Focus experiments on the failing slice (`--tags`, ≥ 8 tasks), add tasks there.

**Verdicts**: better (lo > 0) · worse (hi < 0) · non-inferior (lo > −margin: "didn't break it") · inconclusive ·
insufficient (< 8 tasks). Accept = slice `better` + full dev `better`/`non-inferior`. Fix trials before running (no
peeking); 1 in 20 "wins" is noise. Log hashes, not just names; re-baseline when the model changes.

**Tool variants**: `v1`, `v1+desc`, `v1+errors`, `v1+returns`, `v2` = all three. Model opts: `opt.effort="low"`.

**Vendors**: shared core + measured per-vendor addenda.

`python -m agentlab.evals lint --tools v2 --prompt v2` · `python -m agentlab.evals experiment ... --log docs/experiments/node05.md`
