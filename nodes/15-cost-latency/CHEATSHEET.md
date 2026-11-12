# Node 15 cheat sheet: cost and latency

**Report per outcome**: $/conversation = cost / n · $/resolution = cost / resolved · blended = (cost + human $ ×
unresolved) / n. Exclude provider/timeout errors; include discarded calls (retries, escalations). Free models:
shadow-price the token counts, and say so.

**Caching = prefix**: tools → system → messages. Stable first, dynamic last (timestamps, memory, retrieved docs at
the end). Don't reorder tools; history edits (compaction, windows) miss from the edit; caches are per model and per
effort/thinking setting; below the minimum length nothing caches, silently. Anthropic: write 1.25×, read ~0.1×
(one read repays the write); OpenAI-style: automatic, no write premium. Debug with "first divergence" (or the
provider's cache diagnostics).

**Cascade**: cheap first; escalate on high-stakes tools, parse errors, recent tool errors, empty answers; charge
the discarded call; sticky avoids repeated cold caches. Signals miss confident wrong answers → measure resolution.

**Latency** = Σ calls (TTFT + output ÷ speed) + tools. Levers: fewer turns › shorter outputs/effort › cache ›
smaller/faster model or speed tier (2× price) › streaming (perceived). Report p50 + p95.

**Batch** ≈ 50% off for offline work (stacks with caching). **Self-host** $/1M = GPU $/h ÷ (tok/s × 3600 ×
utilization) × 1e6: utilization decides.

`python -m agentlab.perf bench --configs mid,fast,fast>mid,mid+cache:auto --human-cost 4`
`python -m agentlab.perf doctor RUN_DIR --config fast+cache:timestamp`
`python -m agentlab.perf breakeven --gpu-usd-per-hour 1.2 --tokens-per-second 900 --utilization 0.1 --api-usd-per-mtok 0.4`
