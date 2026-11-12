# Node 01 cheat sheet: LLMs for agent builders

**Latency** ≈ TTFT (network + queue + prefill + thinking) + output_tokens ÷ decode speed. Output length dominates latency.
**Price cliffs**: crossing a long-context threshold re-prices the *whole* request. Stay under it.
**Cost** in agents is dominated by *input* re-sent every turn: Σ over turns of the context size.

**Prompt caching** is a *prefix* match on exact tokens. Layout: `tools → system → stable docs → history → newest`.
Deterministic tool order. No timestamps or IDs near the top. Cache writes can cost more than plain input.
Verify hits in usage (`cache_read_*`), never assume.

**Sampling**: logits ÷ T → softmax → top-k → top-p → draw. T→0 = greedy. Production "T=0" is still
non-deterministic (batching + float non-associativity, MoE). Current Claude API: no temperature; use `effort`.

**Structured outputs** (constrained decoding) guarantee *shape*, not *truth*. Validate semantics in code.

**Training fingerprints**: tool format and harness conventions (vendor-specific) · sycophancy and self-grading
bias · instruction-following is statistical, not a security boundary · rewarded to "finish" (may fake it) ·
knowledge cutoff.

**Reasoning tokens** are output tokens (cost + latency). Pin and report effort in every comparison.
Round-trip thinking blocks unchanged in tool loops.

**Context rot**: longer context + similar distractors + middle position → worse recall. Local runtimes may
silently truncate (`OLLAMA_CONTEXT_LENGTH`). Curate context (Node 06).

**Hallucination** in agents: fabricated args, fabricated *results* ("refund issued"), fabricated capabilities.
Grade from state, not prose (Node 04).

| Wire format | Anthropic | OpenAI-compatible |
|---|---|---|
| tool call | `content[] {type: tool_use, id, name, input: {…}}` | `message.tool_calls[] {id, function: {name, arguments: "…json string…"}}` |
| tool result | user message, `{type: tool_result, tool_use_id, content}` | message `{role: tool, tool_call_id, content}` |
| stop | `stop_reason: tool_use / end_turn / max_tokens / stop_sequence / pause_turn / refusal / model_context_window_exceeded` | `finish_reason: tool_calls / stop / length / content_filter` |
| cache usage | `cache_creation_input_tokens`, `cache_read_input_tokens` | `prompt_tokens_details.cached_tokens` |
