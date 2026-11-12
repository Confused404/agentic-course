# Node 06 cheat sheet: context engineering and memory

**Budget**: call i ≈ S + i·d tokens; a conversation ≈ N·S + d·N²/2 (quadratic). Quality drops long before the limit.
Goal: the smallest set of high-signal tokens for the next step.

**Measure**: tool results usually dominate. `python -m agentlab.context breakdown RUN --task ID`.
Estimate = chars/4 (calibrate); billing = provider usage.

**Transcript ≠ working context.** Keep both. Graders/audits/memory read the transcript; strategies edit the other.

**Four moves**: write (notes, memory) · select (memory read, retrieval) · compress (clear, compact) · isolate (subagents).

**Strategies**: `full` · `window:K[:T]` · `clear:T[:K]` (stub old reads; keep side-effect results) ·
`compact:T[:K]` (summary + last K turns) · `notes=on`.
Cut only at customer turns (never between tool_use and tool_result).

**Compaction prompt** keeps: instructions verbatim (+ SUPERSEDED), facts tools can't fetch, names for things,
actions with ids/amounts/outcomes, open items. Drops: re-fetchable content. No advice. Carry earlier summaries forward.
Failure cap (circuit breaker). Read the summary the model saw.

**Cache**: any edit invalidates from that point on. Naive window = no history cache ever. Act above a trigger, in big
steps. Per-customer content at the END of the system prompt.

**Memory**: write = background extraction (schema) → `memory_policy` (code) → store. Read = inject all (small) /
retrieve (large) / tool. Supersede on change; hard-delete on "forget". Frame as data; grants nothing.
Policy order: kind · length · grounded in customer words · sensitive · authority · duplicate · supersedes own ids.
Every query filters by customer. "Nothing" is the usual extraction result.

**Evals**: plant at turn 2, probe at the end, state-graded; 10/30/50 turns; success, tokens, cache share, $ together.
Multi-session tasks, including ones where NOT remembering is correct.

`--baseline context=full,opt.cache=true --candidate context=compact:12000:4,opt.cache=true --tags len10,len30`
`python -m agentlab.context report runs/experiments/<ts>`
