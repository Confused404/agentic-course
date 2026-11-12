# Node 01: your work

Tags: **[AGENT-OFF]** write it yourself · **[PREDICT]** write before running · **[READ-TRACE]** inspect a trace ·
**[DECIDE]** record a decision · **[LOG]** lab-notebook entry.

---

### 1. [PREDICT] Before anything runs (30 min)
Read TEXTBOOK §1–§9 and answer the self-check *without* opening the answers. Then add one LEARNING_LOG
entry titled "Node 01 predictions" with a numeric prediction and a confidence for each:

| Exp | Predict |
|---|---|
| E1 | Japanese sample tokens ÷ English sample tokens on each vendor. Which vendor counts the JSON schema highest? |
| E2 | TTFT at 32K vs 1K input (ratio). Output tokens/s for each model. Which matters more for total time: 32K input or 400-word output? |
| E1 | (also) Will the two Anthropic models you know of count the same text identically? (Tokenizers change between generations.) |
| E3 | Cost of call 2 as a % of call 1. TTFT change. What will `cache_miss_reason` say for call 3? |
| E4 | Distinct first-tool-call outputs out of 10 at T=0 vs T=1.3. Accuracy at effort low vs high. |
| E5 | Accuracy at pos=0.5, len=30K for each model. Will any model say 4417 (the retired code)? If you opted into Ollama for `local`: will its *reported* prompt tokens match the estimate? |
| E6 | Will any model make parallel tool calls for "compare 4821 and 4822"? Will any OpenAI-format arguments fail to parse? |

### 2. [AGENT-OFF] Write the toy sampler by hand (60–90 min)
File: `agentlab/probe/toy_sampler.py`. The contracts are in its docstring; tests are
`nodes/01-llm-internals/tests/test_toy_sampler.py`. numpy only. No coding agent, no autocomplete
that writes whole functions.

Hints, if stuck:
- Numerical stability: softmax(z) == softmax(z − c) for any constant c.
- top-p: sort descending, cumulative sum, find the first index where the sum reaches p. "Smallest set"
  means include that index.
- Use `rng.choice(len(probs), p=probs)` to draw.

Then run `e0_toy_sampling.py` and **[LOG]** your answer to its closing question. Relate it to TEXTBOOK §4's
explanation of non-determinism at temperature 0.

### 3. Delegate the harness, then review it (90 min)
Start a branch (`make new-ticket N=01`), then tell your coding agent:
> Implement nodes/01-llm-internals/SPEC.md. Follow AGENTS.md. Don't touch toy_sampler.py.

While it works, predict which part of the SPEC it will get wrong (log it). When it finishes:
- Read `parse.py` line by line. Find where an invalid `arguments` string is handled. Would *your* agent loop
  in Node 02 crash on it?
- Read the streaming reassembly in `raw.py`. Why do tool-call arguments need accumulating by `index`?
- `make grade N=01` must be green.

Optional: give the *same* SPEC to your other coding agent (Claude Code vs OpenCode) on a scratch branch
and diff the two implementations. Note which one followed the SPEC more literally.

### 4. Run the experiments (3–4 hours)
Run E1–E6, on at least two vendors. After each one, write a **[LOG]** entry: prediction → result → mechanism.
Specific things to look at:
- **E2**: plot (even by hand) total time against input length, and against output length. Estimate your
  model's decode speed from the data.
- **E3** **[READ-TRACE]**: `make trace` after running. Find `course.usage.cache_read_tokens` on the second call.
  Compute the saving yourself from `config/models.toml` prices. Does it match `cost_usd`?
- **E4**: in part B, compare `output_tokens` across efforts. Was "high" worth it on this question?
- **E5** (if you opted into Ollama for `local`): if the local model did badly, check `reported_prompt_tokens` vs `estimated_prompt_tokens` and the
  `truncated` column before concluding anything about the model. Then set `OLLAMA_CONTEXT_LENGTH=32768`
  (restart `ollama serve`) and re-run just the local model (`--models local`; results append).
  **A null result is possible**: strong hosted models may score ~100% on single-needle recall at 30K. If so,
  run `--hard` (pick the latest of several dated versions). Explain in your log what a null result does and
  doesn't tell you about context rot (hint: §7 lists four aggravating factors; which did the easy version test?).
- **E3**: the `diagnostics` column. Step 3 should name what changed (the system prompt). If step 1 already
  shows a cache *read*, you re-ran within the cache lifetime. Wait a few minutes.
- **E6**: open `runs/node01/wire/*.json` side by side. List five structural differences.

### 5. [DECIDE] Write the report (60 min)
Create `docs/reports/01-model-behaviour.md`:
```
# Model behaviour report (Node 01)
## Setup: models, dates, total spend
## Findings (one paragraph each, with numbers): E1 … E6
## Rules I will follow from now on (at least 5, each tied to a finding)
   e.g. "Tool definitions will be sorted by name: E3 showed a one-character prefix change costs X."
## Vendor differences that my adapter (Node 02) must absorb
## Open questions / what I'd measure next
```

### 6. [DESIGN] E7: your own experiment (≤ 2h, ≤ $0.05)
Pick one question the textbook raised that the experiments didn't answer. Ideas:
- Does **tool definition order** change the cache hit rate? (It should, per §3. Show it.)
- How does **effort** change latency for a trivial question vs the order-4821 question?
- Does a **non-English** user message change tool-call accuracy?
- Does `local`'s tool-call validity change with the number of tools offered (3 vs 15)?

Write `experiments/e7_<name>.py` using the probe library (your coding agent can write the plumbing, but
*you* write the hypothesis, the measurement and the success criterion first, in the log).

### 7. Socratic review
Use the prompt at the end of TEXTBOOK.md. Log the concept you were least solid on.
