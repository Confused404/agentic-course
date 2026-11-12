# Node 15: your work

Cost: tasks 2, 3 and 8 are free. The cache experiment ≈ $0.10 on paid `fast`; the default bench ≈ $1–2 (on free
models: $0, shadow-priced, but ≈ 600 requests).

### 1. [PREDICT] (20 min)
Read TEXTBOOK §1–§4. Then open one Node 04 trial of the support agent (`runs/evals/<dir>/trials.jsonl`, or run
`make eval N=04` on two tasks) and predict in `LEARNING_LOG.md`:
- the share of a typical conversation's input tokens that is system prompt + tool definitions;
- the cache read share you'll get with `cache:auto`, and with `cache:timestamp`;
- for the cascade `fast>mid`: the escalation rate, and whether its cost per *resolution* beats `mid`'s;
- which costs more latency in a support conversation: the number of calls or the time per call.

### 2. [AGENT-OFF] prefix.py (≤ 45 min)
`first_divergence`; grader `tests/test_prefix.py`. **[READ-TRACE]** first, on paper: for these consecutive
requests, where does the prefix first differ, and roughly how many tokens could a cache have served?
(a) call 2 of a conversation vs call 1 (one assistant message and one tool result appended);
(b) the same, after Node 06's sliding window dropped the first exchange;
(c) the same, with a memory block appended to the *end* of the system prompt between the calls;
(d) call 1 of two different customers' conversations.
Which of these is a cost of a design choice you made in an earlier node?

### 3. [AGENT-OFF] economics.py (≤ 45 min)
`percentile` and `unit_economics`; grader `tests/test_economics.py`. **[DECIDE]** then: what does a human-handled
support conversation cost Shopfront? Make an estimate (minutes per ticket × loaded cost per hour, plus the cost of
a customer waiting) and write down where each number came from. That's your `--human-cost`. How large would a
resolution drop need to be to cancel a 50% model-cost saving at your figure?

### 4. Delegate, then review (≤ 2h)
`make new-ticket N=15` → coding agent: *"Implement nodes/15-cost-latency/SPEC.md. Follow AGENTS.md. prefix.py and
economics.py are mine; don't write them."*
Review for: recording happens *inside* the cascade (a discarded cheap answer is still counted); the discarded
answer is charged to the budget; after an escalation, `model`/`provider` are the strong model's; the doctor
compares calls to the same model only; nothing is created before the CLI's validation passes.

### 5. The cache experiment (≤ 1h, ≈ $0.10 paid)
Which command depends on your keys:
```bash
# With ANTHROPIC_API_KEY (direct mode): all four layouts really differ on the wire
.venv/bin/python -m agentlab.perf bench --suite nodes/04-evals/evals/support/regression.yaml \
  --configs fast+cache:off,fast+cache:auto,fast+cache:explicit,fast+cache:timestamp
# OpenRouter with credits: the course's OpenAI-compatible adapter doesn't send Anthropic's cache markers, so use a
# provider that caches automatically (OpenAI models, prompts over ~1,024 tokens) and compare stable vs unstable:
.venv/bin/python -m agentlab.perf bench --suite nodes/04-evals/evals/support/regression.yaml \
  --configs gpt-fast+cache:off,gpt-fast+cache:timestamp
# then
.venv/bin/python -m agentlab.perf doctor runs/perf/<dir> --config <one of the configs>
```
That's 11 tasks × the layouts. On free models it runs too, but free providers rarely report cache hits, so the
cache column stays near 0%; the doctor's *prefix* analysis still works (it reads the recorded requests), and it
says when a hit was possible but nothing was read, and the likely reasons.
**[LOG]** for one conversation per layout, every call's cache read share and the doctor's reason. Was `off`
really zero (and on which provider)? What did `explicit` add over `auto` (direct mode), and when would it matter?
Compute, from the usage numbers, how many reads it took to repay the write premium. Stretch: make your Node 02
OpenAI-compatible adapter send `cache_control` on the system prompt for `anthropic/*` models on OpenRouter (check
OpenRouter's prompt-caching docs), and rerun the four Anthropic layouts through it.
**[LOG]** for one conversation per layout, every call's cache read share and the doctor's reason. Was `off`
really zero? What did `explicit` add over `auto`, and when would it matter (hint: what happens to `auto` when the
conversation part changes)? Compute, from the usage numbers, how many reads it took to repay the write premium.

### 6. The bench and the cascade (≤ 2h, ≈ $1–2)
```bash
.venv/bin/python -m agentlab.perf bench --human-cost <your figure>
```
In free mode `fast` and `mid` are the same free model, so the quality columns can't differ between them; the
cost columns are shadow prices (fast as Haiku, mid as Sonnet), which is what the cost questions need.
**[LOG]** the table against your predictions. For the cascade: list the escalation reasons and look at three
conversations that did **not** escalate but failed (`doctor --config 'fast>mid' --task <id>` and the trial's
replies): which signal would have caught them, and what would it cost? **[DECIDE]** change one thing in the cascade
(`nosticky` is a config option; a signal or `error_lookback` means editing the agent-built `router.py`, which is
fine here) and re-run only the two cascade configurations. Is the difference bigger
than the noise (Node 04)? Be explicit about what one trial on 28 tasks can and can't show.

### 7. [READ-TRACE] Where the seconds go (≤ 30 min; the last run ≈ $0.20 paid)
From `trials.jsonl` of task 6, for `mid` and for the cascade: the p50 and p95 conversation latency, the mean
number of calls per conversation, and the per-call latency (`extra.calls[*].latency_s` minus `wait_s`; the report
prints its p50/p95). Note that a "conversation" here is every scripted customer turn of a task, so long scripts
have long latencies; and in free mode `wait_s` is the rate-limit pacing, which says nothing about the model. Which
explains the p95 better: more calls, or slower calls? Name the lever from TEXTBOOK §4 you'd pull first, and what it
would cost. Then run `mid+effort:low` on the regression suite: what moved, latency or resolution?

### 8. Self-hosting arithmetic (≤ 20 min, free)
```bash
.venv/bin/python -m agentlab.perf breakeven --gpu-usd-per-hour 1.20 --tokens-per-second 900 \
  --utilization 0.1 --api-usd-per-mtok 0.40
```
Two honest-number caveats first. `--tokens-per-second` is the server's total throughput across concurrent
requests, usually quoted for *output* (decode); reading the prompt (prefill) is many times faster per token. And
API prices differ for input and output, so `--api-usd-per-mtok` should be a *blended* price: from task 6, take the
input:output token ratio of a support conversation (mostly input) and weight the two prices by it. Then try
utilizations of 0.05, 0.3 and 0.9. **[LOG]** at which utilization the GPU beats the API, and what Shopfront's
support traffic (busy days, quiet nights) means for that. If you do elective [E5](../../electives/E5-self-hosting/README.md), replace the
throughput with the tokens per second you measured.

### 9. [DECIDE] ADR 0012 (≤ 30 min)
`docs/adr/0012-cost-and-latency.md`: the configuration you'd ship and its cost per resolution and blended cost
(with your human-cost figure and its sources); the cache layout and what must never go before the cached prefix;
the escalation signals, what they miss, and how you'd notice; your p95 target and the lever for it; the budget
caps and what happens when one is hit; which offline jobs go to a batch API. Include the bench table and say
what it can't show.
