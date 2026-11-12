# Node 01 Textbook: LLMs for agent builders

> **Scope.** This is not a machine-learning course. You will not see backpropagation or attention
> equations. You *will* learn the handful of mechanisms that explain almost every surprising thing an
> agent does: why a prompt costs what it costs, why a cache misses, why "temperature 0" is not
> deterministic, why a model confidently reports a refund it never issued, why a 1M-token context
> doesn't behave like 1M tokens of memory. Each section ends with **"So, as an agent builder…"**:
> the practical rule the mechanism implies.

## Learning objectives
By the end of this node you can:
1. Explain what happens between your `messages.create(...)` call and the response, in terms of
   tokens, a chat template, prefill and decode.
2. Predict, before measuring, how prompt length, output length and caching affect latency and cost.
3. Implement temperature and nucleus (top-p) sampling, and explain why identical requests can
   still produce different outputs.
4. Explain tool calling and structured outputs as *trained formats plus parsing* (and sometimes
   constrained decoding), and predict how they fail.
5. Connect pretraining vs post-training to agent behaviours: sycophancy, self-evaluation bias,
   instruction-following-is-not-security, vendor differences in tool use.
6. Explain context degradation ("context rot") and hallucination mechanistically, and name the
   engineering responses that later nodes build.

---

## §1 The model is a function from tokens to a probability distribution

At its core a language model does one thing: given a sequence of tokens, it outputs a probability
distribution over the **next** token. Everything else (chat, tools, reasoning, JSON) is built on
top of that one operation by (a) formatting conventions learned in training and (b) code in the
serving stack.

Generation is a loop. This is the first "agentic loop" you'll meet, and it lives inside the model server:

```
tokens = tokenize(rendered_prompt)
while True:
    probs = model(tokens)              # distribution over ~100k–260k possible next tokens
    next_tok = sample(probs, params)   # §4
    if next_tok is a stop token or len(output) == max_tokens: break
    tokens.append(next_tok)
```

### The chat template: your messages become one long string
The API accepts structured messages (`system`, `user`, `assistant`, tool definitions, tool results).
The model never sees that structure. The server **renders** it into a single token sequence
using a *chat template*: special delimiter tokens that the model was trained to recognise.
A simplified, vendor-neutral illustration:

```
<|system|>You are Shopfront's support assistant...
# Tools
{"name": "lookup_order", "description": "...", "parameters": {...}}
<|end|>
<|user|>Where is order 4821?<|end|>
<|assistant|>
```

The model continues from `<|assistant|>`. If it was trained to call tools by emitting something like
`<|tool_call|>{"name": "lookup_order", "arguments": {"order_id": 4821}}<|end|>`, the server
**parses** that text back into the structured `tool_use` / `tool_calls` object you receive.

Real templates differ by vendor and model family, and closed-model templates are not published.
The structure above is what matters:

1. **System prompts, tool definitions and tool results are all just tokens in the context.**
   The model has no separate channel for "instructions" versus "data". Models *are* trained on an
   instruction hierarchy (system above user, user above tool output), which makes them more likely
   to ignore instructions in a tool result. That is a statistical tendency, not a security boundary.
   This is the root of prompt injection (Node 08).
2. **Tool calling is a learned output format plus a parser.** When it fails, it fails like
   any parser: malformed JSON, a tool name that doesn't exist, arguments in the wrong types, or
   a tool call written as plain text because the model drifted out of the trained format.
3. **For open-weights models, the template is your responsibility (or Ollama's).** A model
   served with a wrong or outdated template can "support tools" on paper and fail constantly
   in practice. If a local model's tool calls are bad, check the template/runtime version before
   blaming the model.

> **So, as an agent builder:** treat every model output as untrusted text that *usually* parses.
> Validate tool names and arguments against the schema before executing (Node 02), and
> remember that everything you put in context, including tool results, can influence the model.

---

## §2 Tokens: the unit of cost, limits and weirdness

Models don't see characters or words. They see **tokens**: chunks produced by a tokenizer (usually
a byte-pair-encoding variant) trained to compress common text. Common English words are often one
token; rare words, code identifiers, numbers and non-Latin scripts break into several.

Rules of thumb (English prose): ~4 characters per token, ~0.75 words per token. But:

| Text | Why it inflates |
|---|---|
| JSON and tool schemas | punctuation, quotes and keys each cost tokens; whitespace too |
| Code | identifiers like `max_refundable_cents` split into many pieces |
| Long numbers and IDs | `4821`, `toolu_01A9...`, UUIDs: digits group unpredictably |
| Non-English text | French ~1.2–1.5×, Japanese/Chinese can be 2–3× English for the same meaning |
| Emoji, rare Unicode | a single glyph can be several tokens |

**Every vendor has its own tokenizer, and tokenizers change between model generations.** The same
prompt can be, say, 1,000 tokens on one model and 1,150 on another, even from the same vendor: Anthropic's
Haiku 5.5 was reported to produce roughly 30% more tokens than Haiku 4.5 for the same text. Price per
million tokens is only comparable *after* you count tokens with each model's tokenizer, and you must
re-count after every model upgrade. That's why Experiment E1 measures counts through each provider's
own usage report.

Tokenization also explains some classic model weaknesses: counting letters in a word, reversing
strings, exact arithmetic on long numbers, and copying long IDs without a typo. The model never
saw those characters individually. In agents this shows up as **transcription errors in IDs**:
the model "copies" order `4821` into a tool argument as `4812`. The remedy is design, not
hope: keep IDs short, validate them in tools, and prefer selecting from options the tool returned
over retyping.

> **So, as an agent builder:** measure tokens with the vendor's own count. Budget tool schemas
> and tool results as first-class token costs (they are often most of the context in an agent).
> Never ask the model to do work that tokenization makes hard when code can do it.

---

## §3 Prefill, decode, and the KV cache: where latency and caching come from

A request has two phases with very different performance characteristics:

**Prefill.** The model processes all *input* tokens. This is highly parallel: the whole
prompt goes through the network at once, so it's fast per token and compute-bound. Its cost
grows faster than linearly at very long lengths, because attention compares every token with every
earlier one.

**Time to first token (TTFT)** ≈ network + queueing + prefill (+ thinking, for reasoning models,
which generate hidden tokens before any visible output). For short prompts, network and queueing
dominate. Prefill dominates only for long prompts. E2 records both "first visible token" and
"first token of any kind" so you can see the thinking gap.

**Decode.** The model generates output tokens **one at a time**. Each new token requires another
pass through the model. This is sequential and limited by memory bandwidth, so output is slow
per token, typically tens to a few hundred tokens per second.

A useful first-order latency model:

```
latency ≈ TTFT(input_tokens) + output_tokens / decode_speed
          (grows slowly with input)  (dominates for long answers)
```

So in agents, **output tokens are the expensive part of latency**, and input tokens are the
expensive part of *cost* (because agents re-send a growing context every turn). An agent with 20
turns and a 30K-token context sends ~600K input tokens in total, even if each answer is short.
You will measure both effects in E2.

**Price cliffs.** Some models charge a higher rate for *every* token of a request once the prompt
crosses a threshold (for example, Haiku 5.5 is 5× more expensive above 100K prompt tokens as of this
writing; `agentlab/costs.py` implements it). An agent whose context drifts past the line doesn't get
a bit more expensive. Every call costs several times more. Keeping contexts under thresholds is one
of the concrete goals of compaction (Node 06).

**Why local models run out of memory.** The KV cache (below) takes, per token, roughly
`2 × layers × kv_heads × head_dim × bytes_per_value`. For a mid-size model that's on the order of 100 KB
per token, so 32K tokens of context can need several GB *on top of* the weights. That's why local
runtimes default to small context windows.

### The KV cache
During prefill the model computes, for every token at every layer, intermediate vectors called
**keys and values**. Decode re-uses them: each new token only computes its own and "attends" to
the stored ones. That store is the **KV cache**.

**Prompt caching** (a provider feature) keeps the KV cache of a prompt *prefix* around for a few
minutes. If your next request starts with exactly the same tokens, prefill for that prefix is
skipped. You pay a fraction of the input price for cached tokens and TTFT drops.

The key word is **prefix**. The cache is keyed on the exact token sequence from the start of the
prompt. Change one token early and everything after it is a miss. The consequences shape
how you lay out agent prompts:

```
[ tools ][ system prompt ][ stable reference docs ][ conversation history ...  ][ newest turn ]
 most stable  ─────────────────────────────────────────────────────────────►  most volatile
```

- Put stable content first and volatile content last.
- **Tool definitions usually come first in the rendered prompt.** If you build the tool list from a
  dict or set with unstable ordering, or add/remove a tool mid-conversation, you invalidate the cache
  for the *entire* request. Deterministic tool ordering is a cost optimisation.
- Don't put timestamps, request IDs or "current time" at the top of the system prompt.

Providers expose caching differently (this changes, so check the node appendix): some cache
automatically above a minimum prefix length and report `cached_tokens`; Anthropic lets you mark
cache breakpoints (or apply one automatically), reports `cache_creation_input_tokens` /
`cache_read_input_tokens` separately, and can explain *why* a request missed. Writing to the cache
can cost **more** than a normal input token, so caching a prefix you never reuse loses money. E3
measures this.

> **So, as an agent builder:** design prompts as an append-only log with a stable prefix. Count
> output tokens when you care about latency and input tokens when you care about cost. Verify cache
> hits in the usage numbers; don't assume them.

---

## §4 Sampling: how a distribution becomes a token

The model outputs **logits**, one real number per vocabulary entry. To pick a token:

1. **Temperature** divides the logits: `z_i / T`. Then **softmax** turns them into probabilities:
   `p_i = exp(z_i/T) / Σ_j exp(z_j/T)`.
   - `T → 0`: the distribution collapses onto the argmax (greedy decoding).
   - `T = 1`: the model's "native" distribution.
   - `T > 1`: flatter, so more surprising tokens get picked.
2. **Truncation** removes the tail before sampling:
   - **top-k**: keep the k most likely tokens.
   - **top-p (nucleus)**: keep the smallest set of tokens whose probabilities sum to ≥ p.
3. Renormalise and **sample** one token.

You will
implement exactly this in `agentlab/probe/toy_sampler.py` (AGENT-OFF), then run it on a toy
distribution to *see* the effect of each knob.

Real runtimes vary the recipe. Some apply truncation before temperature (llama.cpp does by default),
and local runtimes often add **min-p** (drop tokens below a fraction of the top token's probability).
The concepts are the same; the exact output for a given setting is runtime-specific.

### Why "temperature 0" is not deterministic
Greedy decoding is deterministic in principle. In production it often isn't, because:
- **Floating-point non-associativity + batching.** Your request is batched with other people's.
  Different batch shapes change the order of floating-point additions inside GPU kernels, which
  changes logits in the last few bits, which can flip a near-tie between two tokens. Once one token
  differs, everything after it diverges.
- **Mixture-of-experts routing**: experts have capacity limits per batch, so which expert handles *your*
  token can depend on *other people's* requests in the same batch. Different hardware and replicas add
  more variation.
- `seed` parameters, where offered, are best-effort.

Practical consequence: **with hosted APIs you cannot make an LLM system reproducible by turning a knob.**
(Self-hosted inference servers can offer batch-invariant kernels that make greedy decoding deterministic,
at some throughput cost. That's an option for you, not for your API vendor.) You make the system
*measurable* instead: run each eval case several times and report rates (Node 04).

### Where the knobs went
As of this writing, several providers' current models no longer accept `temperature` / `top_p` at all
(the Anthropic Messages API for current Claude models is one; see the appendix). OpenAI's reasoning models likewise ignore or reject temperature. The trend is driven by reasoning
models (§6): sampling is tuned by the provider, and you control **how much the model thinks** (an
`effort` or `reasoning_effort` setting) rather than how randomly it samples. Local runtimes and many
non-reasoning hosted models still honour temperature, so E4 explores both kinds of control.

**An endpoint that *accepts* a parameter may not *honour* it.** Routers and compatibility layers often
drop unsupported parameters silently. If a knob seems to do nothing, verify that it reached the model
(E4 asks OpenRouter to fail rather than drop it).

### Structured outputs and constrained decoding
If you ask for JSON in the prompt, the model *usually* complies. **Constrained decoding** makes it
certain: at each step, the server masks out every token that would make the output invalid under a
grammar (e.g. compiled from your JSON Schema), so only valid continuations can be sampled. This
guarantees the output **parses and matches the schema's shape**. It does *not* guarantee the content
is correct: a constrained model will happily produce a schema-valid refund amount that is wrong.

Three caveats agents hit in practice:
- **The guarantee holds only if generation completes.** Hitting `max_tokens` (or a refusal) yields
  truncated, invalid JSON. Check `stop_reason` before parsing.
- **Constraining can lower quality.** Masking tokens distorts the model's distribution, so the
  "nearest valid" token may not be what it would have said.
- **Field order matters.** The model writes keys in schema order and commits to earlier keys first. Put a
  `reasoning` or `explanation` field *before* the answer fields if you want the answer conditioned on it.

Older "JSON mode" features only guaranteed syntactically valid JSON, not your schema. Strict
schema modes may restrict which JSON Schema features you can use (e.g. require
`additionalProperties: false`, limit recursion). Tool-call arguments may or may not be constrained
depending on provider and settings, so **validate them anyway**.

> **So, as an agent builder:** for agents, sampling randomness is mostly a source of variance to
> *measure*, not a dial to tune. Use structured outputs where you parse model output in code, and
> keep semantic validation (does this order exist? is the amount ≤ refundable?) in your own code.

---

## §5 Training: why models behave the way they do

You don't need the algorithms. You need the shape of the pipeline, because each stage leaves
fingerprints on agent behaviour.

**Pretraining.** Next-token prediction on a vast corpus. Produces knowledge, fluency, and the ability
to continue *any* text plausibly, including text that looks like instructions. Knowledge stops
at a cutoff date.

**Supervised fine-tuning (SFT).** Training on curated demonstrations: conversations in the chat
template, tool calls in the tool format, refusals, formatting. This is where "assistant-ness" and
the **specific tool-call format** come from.

**Reinforcement learning from feedback.**
- From human/AI **preference** judgments: the model learns what raters prefer. A side effect is
  **sycophancy**: agreeing with the user, praising their work, and rating its *own* output generously.
- From **verifiable rewards** (tests pass, the math checks, the task in a sandbox succeeded): this
  is how current models learn long multi-step tool use, persistence and "reasoning".

Fingerprints you will meet in this course:

| Training fact | Agent behaviour | Where we deal with it |
|---|---|---|
| Tool format learned in SFT/RL, differs per vendor | Same tools, different reliability across vendors; open models more brittle | Node 02 adapters, Node 04 cross-model matrix |
| RL on particular harnesses (bash, file-edit tools) | Models are better with tool shapes like the ones they were trained on | Node 03 edit tool, Node 05 tool design |
| Preference training → sycophancy | Agent agrees with a wrong customer; grades its own work too kindly | Node 04 judges, Node 12 generator/evaluator split |
| Instruction following is *learned*, statistical | Text that looks like instructions in a tool result can be followed | Node 08: the fix must be architectural |
| Rewarded for completing tasks | Can "complete" by claiming success, editing tests, or skipping checks | Node 03 guardrails, Node 12 independent verification |
| Knowledge cutoff | Confidently outdated facts about APIs, prices, policies | Tools/retrieval for anything current (Node 07) |

> **So, as an agent builder:** model "personality" is mostly training residue. Don't argue with
> it in the prompt. Design around it: verify independently, keep authority in code, and measure
> each vendor rather than assuming.

---

## §6 Reasoning models

"Reasoning" or "thinking" models generate intermediate tokens before (and, in agent loops, between)
their visible answers. They're trained with RL to use those tokens productively: planning,
checking, backtracking.

What matters operationally:
- **Thinking tokens are output tokens.** You pay for them and they cost latency (decode is the slow
  phase). They may be hidden, summarised, or returned as blocks depending on provider.
- **Control is by effort/budget**, not temperature: e.g. `effort: low | medium | high`, or a
  thinking-token budget. Defaults differ by model, which silently skews naive comparisons.
- **Interleaved thinking.** In tool loops, some models think again after each tool result. Some
  providers require you to **pass the reasoning blocks back unmodified** (often with a cryptographic
  signature) in the next request, or the request fails or quality drops. Others don't return reasoning
  state at all in their classic API: OpenAI's Chat Completions doesn't, while its Responses API carries
  encrypted reasoning items, and OpenRouter exposes `reasoning_details`. That's why the course's
  `ThinkingBlock` has an opaque `provider_data` field, plus a `provider` tag, which your adapter must
  round-trip or drop (Node 02).
- **More effort is not monotonically better.** For simple lookups it adds cost and latency with no
  accuracy gain; for multi-condition policy questions (order 4821: damaged? which window?) it can
  matter a lot. E4 measures this on a real Shopfront question.

> **So, as an agent builder:** treat effort as a per-task cost/quality dial you set from eval
> results. Never compare two models without pinning (and reporting) their effort settings.

---

## §7 Attention and context: why 1M tokens isn't 1M tokens of memory

**Attention** lets every token "look at" every earlier token and pull in information. It's why the
model can use something from 50 pages ago. It is also why long contexts are expensive: the work
grows with context length.

Advertised context windows are now very large (hundreds of thousands to 1M tokens). But
*capacity* is not *reliable use*. Recall and reasoning over context degrade as:
- the context gets longer,
- relevant information sits among many **similar distractors** (e.g. three versions of a policy),
- the information is in the middle rather than at the start or end (a well-documented position
  effect, though its size varies by model and generation),
- the task requires *combining* several scattered facts rather than retrieving one.

Practitioners call the overall effect **context rot**: each additional token has diminishing,
eventually negative, returns. The model's attention is a finite budget, and filler competes with signal.

For local models there is a more brutal failure: **silent truncation.** Local runtimes size their
default context to your hardware. As of this writing, Ollama defaults to 4,096 tokens on machines
with under 24 GB of VRAM. A 30K-token prompt is cut down without an error, and the model answers from
whatever survived. E2 and E5 flag it by comparing the prompt tokens the runtime *reports* with what
you sent.

> **So, as an agent builder:** context is a scarce resource to *curate*, not a bucket to fill.
> This is the entire motivation for context engineering (Node 06): compaction, note-taking,
> retrieval on demand, and sub-agents with clean contexts.

---

## §8 Hallucination

A model produces the most plausible continuation. When the true answer isn't available, a plausible
fabrication often scores higher than "I don't know", because training rewarded answering
and confident completions. Hallucination is a **calibration and objective** problem, not a bug you can
prompt away. Prompts can reduce it ("say you don't know if…"); they can't eliminate it.

In agents, the dangerous forms are:
- **Fabricated tool arguments:** an order ID the user never gave.
- **Fabricated tool results:** "I've issued your refund" when no `issue_refund` call happened,
  or it returned an error. This one is invisible if you only read the final message.
- **Fabricated capabilities:** "I've emailed you a label" when there is no email tool.

The engineering responses: ground answers in tool results; give the model explicit "unknown" paths
(e.g. an `escalate_to_human` tool); and **grade outcomes from state** (the database, the audit log),
never from the agent's own description of what it did. Node 04 makes this the default.

---

## §9 Wire formats: what actually goes over the network

Same tool, same question, three providers (simplified):

**Anthropic Messages.** The assistant message's content is a list of blocks. A tool call is a
block with an `input` **object**. Tool results go back in a `user` message as `tool_result`
blocks referencing the `tool_use` id.
```json
{"role": "assistant", "content": [
  {"type": "text", "text": "Let me look that up."},
  {"type": "tool_use", "id": "toolu_01…", "name": "lookup_order", "input": {"order_id": 4821}}]}
```

**OpenAI-compatible Chat Completions** (OpenAI, OpenRouter, Ollama, most hosts). Tool calls are a
separate `tool_calls` array, and `arguments` is a **JSON string you must parse** (it can be invalid).
Results go back as messages with role `tool` and a `tool_call_id`.
```json
{"role": "assistant", "content": null, "tool_calls": [
  {"id": "call_1", "type": "function",
   "function": {"name": "lookup_order", "arguments": "{\"order_id\": 4821}"}}]}
```

**Local models via Ollama's OpenAI-compatible endpoint** use the second format. In practice, depending
on model and runtime version: argument strings that don't parse, tool calls written into `content` as
text, (on some older runtimes) a `finish_reason` of `stop` even though there were tool calls, and
parallel calls that some models never make.

Other differences to note in E6: where the system prompt goes, stop/finish reason vocabularies,
usage field names, how parallel tool calls are represented, and how errors are signalled. (OpenAI's
newer *Responses* API is a third, item-based format. Node 02's adapter pattern absorbs it the same way.)

> **So, as an agent builder:** write parsing as pure functions over the raw payload, test them on
> recorded payloads (including broken ones), and normalise everything at the boundary. That is
> exactly the adapter you build in Node 02.

---

## Design trade-offs (the decisions this node prepares you for)

| Decision | Option A | Option B | What decides it |
|---|---|---|---|
| Measure tokens | vendor's count (accurate) | `len(text)/4` (free, instant) | Use the estimate for budgeting and the vendor count for billing and comparisons |
| Determinism | chase it (T=0, seeds) | accept variance, measure rates | You can't fully get it; measure |
| Structured output | strict schema (constrained) | prompt + validate + retry | Strict when available and your schema fits its subset; always validate semantics |
| Effort | high everywhere | per-task, from evals | Cost/latency vs accuracy per task type |
| Context | include everything "just in case" | curate | Context rot + cost: curate |

---

## Common failure modes and debugging

| Symptom | Likely cause | Check |
|---|---|---|
| Cache read tokens = 0 on the second call | prefix changed (tool order, timestamp), prefix below minimum length, or TTL expired | diff the two requests' first N tokens; read `cache_miss_reason` (Anthropic) |
| Local model "ignores" half the prompt | context truncated by runtime default | prompt token count in usage vs what you sent; set `OLLAMA_CONTEXT_LENGTH` |
| `json.loads` fails on tool arguments | OpenAI-format `arguments` is a model-generated string | catch, return an error *to the model*, let it retry (Node 02) |
| `400: temperature not supported` | provider removed sampling params for that model | use `effort`; adapters must drop unsupported opts (Node 02) |
| Empty answer, `stop_reason` = max_tokens/length | reasoning used the whole output budget | raise `max_tokens`, lower effort; never score truncation as "wrong" |
| Temperature "does nothing" | parameter accepted but ignored (reasoning model, router dropped it) | verify the param reached the model; on OpenRouter use `require_parameters` |
| Identical requests, different answers | §4 non-determinism | measure across N runs; don't debug a single sample |
| Cost far above estimate | thinking tokens; context re-sent every turn; long-context price tier | read usage per call in the trace; check `reasoning_tokens` |

---

## Self-check
Answer before running the experiments. Then again after.

1. A prompt of 40K tokens returns a 50-token answer in 2.1s. The same prompt asking for a
   1,000-token answer takes 9s. Roughly what is the decode speed, and what does TTFT look like?
2. You add the current timestamp to the top of your system prompt "for context". What happens to
   your cache hit rate, and why?
3. Why might an agent misspell an order ID it was given verbatim two turns ago?
4. A strict JSON-schema structured output returns `{"amount_cents": 8000}` for a refund that should
   be 4550. Did constrained decoding fail?
5. Your support agent tells the customer "Done! Your refund is on its way." What *two* things
   must you check before believing it?
6. Why does a model's tendency to follow instructions found in a product review follow from how it
   was trained, and why does that imply the defence can't be "tell it not to"?
7. You compare Model A (default effort high) and Model B (default effort medium) and conclude A is
   smarter. What's wrong with the comparison?

<details><summary>Answers</summary>

1. ~950 extra tokens in ~6.9s, so roughly 140 tokens/s decode. TTFT plus 50 tokens ≈ 2.1s, so TTFT
   is about 1.7s, mostly prefill of 40K tokens. Output length dominates latency.
2. It drops to ~0 for everything after the timestamp, i.e. almost the entire prompt, because the
   cache is keyed on the exact prefix and the timestamp changes every request. Put volatile
   content at the end.
3. Tokenization: the ID is a few digit-chunk tokens; copying is a prediction, not a memcpy, and similar
   numbers in context (other order IDs) compete. Validate IDs in tools; prefer short IDs.
4. No. Constrained decoding guarantees shape, not truth. The value is schema-valid but wrong; semantic
   checks belong in your code (and the service: `issue_refund` caps at refundable amount).
5. That `issue_refund` was actually called with the right arguments (trace) **and** that the
   state changed (refunds table / audit_log). Final text is not evidence.
6. Instruction following was learned statistically from text that looks like instructions; the
   model has no separate channel distinguishing your instructions from data. A prompt is just more
   text competing in the same channel, so the fix is limiting what the agent can *do* after reading
   untrusted text (Node 08).
7. Effort is a confound: you compared configurations, not models. Pin effort (and report it), and
   use multiple trials.
</details>

## Socratic review prompt
Paste into Claude Code or OpenCode after the experiments:
> Read nodes/01-llm-internals/TEXTBOOK.md and my LEARNING_LOG.md entries for Node 01. Don't write
> code. Quiz me with 6 questions, one at a time, that connect my experimental results to the
> mechanisms (prefill/decode, KV cache, sampling, training, context rot). Push back if my
> explanation is vague. End with the one concept I seem least solid on.

## Further depth (optional, in-course)
- Re-run E4 with your own toy distribution where two tokens are nearly tied. At what temperature
  does the "wrong" one start winning 10% of the time? That near-tie is what batching noise flips.
- In E5, add a second needle that *contradicts* the first, earlier in the haystack. Which does each model
  report? This previews the archived-vs-current policy problem in Node 07.
