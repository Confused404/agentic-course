# Node 15 TEXTBOOK: cost and latency

An agent's cost and latency come from the same place: the number of model calls, and how many tokens each one
reads and writes. So the levers overlap. Fewer calls and shorter prompts make a run cheaper *and* faster; a bigger
model makes it better, slower and dearer. This node measures before it changes anything, then pulls the levers
that matter most for an agent: prompt caching, routing between models, and fewer round trips.

## §1 Where the money goes
**Input dominates.** Each call in an agent loop resends the whole conversation: system prompt, tool definitions,
every earlier message and tool result. A conversation of `n` calls reads roughly `n × (fixed + growing history)`
input tokens: the history part grows with the square of the number of calls. Output is priced higher per token
(typically 5×) but is usually a few hundred tokens per call. Look at your Node 06 context breakdown: for the
support agent the fixed part (system + tools) is a large share of every call, which is exactly what caching is for.

**Measure per call, report per outcome.** A per-call cost is an engineering number. The business number is cost
per *resolved* conversation, and the honest version includes what happens to the unresolved ones:

```
cost per conversation = total model cost / conversations
cost per resolution   = total model cost / resolved conversations
blended cost          = (total model cost + human cost × unresolved) / conversations
```
A model that costs half as much per call but resolves 80% instead of 90% doubles the human workload on the
remaining customers. At $4 of agent time per handed-over conversation, a 10-point drop in resolution adds $0.40
per conversation: more than the entire model bill. Pick a human-cost figure, write down where it came from, and
put it in every comparison (`economics.py`, YOU_DO task 3).

**Count what you throw away.** Retries (Node 14), cascade escalations (§3) and judge/simulator calls (Node 04)
all cost money without showing up as "the answer". The bench records every call at the model-wrapper level, so a
discarded answer still appears in the bill.

**Shadow prices.** On free models everything costs $0, which makes cost experiments meaningless. The bench can
price the free models' token counts as the paid models the aliases stand for. It's an estimate (another model uses
a different number of tokens, and tokenizers differ), and reports say so.

## §2 Prompt caching
Providers keep the processed state of a prompt's *prefix* for a few minutes. If the next request starts with the
same tokens, that part is read from cache: much cheaper and faster. The rules that follow from "prefix":

- **Order is tools → system → messages** (Anthropic documents exactly this order; OpenAI-style caches also match
  from the start of the request). A change anywhere invalidates everything after it: reorder a tool and nothing
  is reused.
- **Stable first, dynamic last.** Timestamps, per-customer facts, retrieved documents and memory belong *after*
  the stable instructions (Node 06 put the memory block at the end of the system prompt for this reason). A
  "Current time: 09:30:05" at the start of the system prompt makes every request unique after the tools.
- **Don't rewrite history.** Compaction (Node 06) and sliding windows edit earlier messages; the next call misses
  from the edit point. That's a real cost of those strategies, worth measuring.
- **Same model, same settings.** Caches are per model; switching models (a cascade escalation) starts cold.
  Changing reasoning effort or thinking settings also invalidates message caches on Anthropic's models.
- **Minimum length.** Prompts below a model-specific minimum (hundreds to a few thousand tokens) are never cached,
  silently. Check `cache_read`/`cache_write` in the usage, not your intentions.

**Prices.** Anthropic charges a premium to *write* (1.25× input for the 5-minute cache) and a large discount to
read (0.1×, or less on some models); one read already repays the write premium. OpenAI-style automatic caching
has no write premium and discounts reads. Either way, cached tokens are also processed faster: time to first
token drops on long prompts.

**Explicit vs automatic.** On Anthropic you mark breakpoints (`cache_control`) or turn on automatic caching (one
top-level marker whose breakpoint follows the end of the conversation). An explicit breakpoint after the system
prompt keeps tools + system cached even when the conversation part misses. OpenAI-compatible providers cache
automatically; through a router like OpenRouter, hits depend on the request reaching the same provider, and
Anthropic models still need cache markers in the request (which the course's OpenAI-compatible adapter doesn't
send: YOU_DO task 5 says how to run the experiment anyway).

**Debugging misses.** The question is always "where did this request first differ from the last one?".
`first_divergence` answers it from the recorded requests (YOU_DO task 2), and the cache doctor applies it to every
call of a conversation. The shared prefix is an *upper bound* on what could be read: a provider only reads back a
prefix that an earlier request wrote at a breakpoint. So when the prefix matches and nothing is read, look at the
rest: was caching requested, did the options change, did the entry expire, did the request reach another server? Anthropic now offers a similar server-side diagnostic (APPENDIX); yours works for any
provider and any recorded run.

## §3 Routing and cascades
Most support turns are easy ("where's my order?"); a few are expensive to get wrong (refunds, cancellations,
angry customers). Paying the strong model's price for every turn is the simple, expensive choice. Two ways to
spend less:

- **Route up front**: classify the conversation (Node 09's router) and send it to one model. Cheap and simple; it
  can't react to a conversation that turns hard halfway.
- **Cascade**: ask the cheap model, check its answer against *signals*, and re-ask the strong model when a signal
  fires. This node's signals: the answer wants a high-stakes tool, its tool arguments didn't parse, a recent tool
  call failed, or the answer is empty.

What a cascade costs: the discarded cheap call (paid for), a second round trip (latency), and a cold cache on the
strong model. *Sticky* escalation (stay on the strong model for the rest of the conversation) pays those once
instead of every time. What a cascade can't do: notice a cheap answer that is confidently wrong and fires no
signal ("Your order has shipped" when it hasn't). That's why the bench measures resolution with the Node 04
graders, not just the escalation rate. Model-graded signals (asking a model "is this answer right?") catch more and
cost a call each; measure before adding one.

## §4 Latency
For one model call: **time to first token** (queueing plus reading the prompt; grows with prompt length, shrinks
with cache hits) plus **output tokens ÷ output speed**. For an agent: the sum over its calls, plus tool time. So
the biggest lever is usually the number of round trips, not the model: a four-call answer on a fast model can be
slower than a two-call answer on a slower one. Ways to cut it, roughly in order of payoff:

1. **Fewer turns**: better tools (Node 05: one tool that returns what the model needs instead of three), parallel
   tool calls in one turn, no "let me check..." preambles.
2. **Shorter outputs**: tight `max_tokens`, lower reasoning effort where quality holds (measure it).
3. **Cache the prefix**: faster time to first token on long prompts.
4. **A smaller or faster model**, or a paid speed tier: Anthropic's fast mode and OpenAI's priority processing
   trade a higher price for more output tokens per second (APPENDIX). Speed tiers raise output speed, not time to
   first token.
5. **Streaming**: doesn't make the answer faster, makes it *feel* faster (Node 17).

Report **p50 and p95**, not the mean: the mean hides the tail, and the tail is what customers complain about.
Tails come from long conversations, retries (Node 14), escalations, and provider queueing; the bench's records tell
you which.

## §5 Measuring configurations
The bench runs the same Node 04 support tasks under several configurations (models, cascades, cache layouts,
effort), interleaved so a slow minute hits all of them, and reports per configuration: resolution rate, cost per
conversation, cost per resolution, blended cost, p50/p95 latency, calls and prompt tokens per conversation, cache
read share, escalation rate, and the Pareto front on (resolution, blended cost).

Everything Node 04 said about noise applies: 28 tasks and one trial is a smoke test. A 3-point difference in
resolution is noise; a 40% difference in cost per conversation usually isn't (costs vary much less than
verdicts). Decide on cost from the bench; decide on quality only with paired comparisons and intervals (Node 04's
`compare`, Node 05's experiments).

## §6 Batches and self-hosting
**Batch APIs** run requests asynchronously (minutes to hours) at about half price, and caching discounts stack on
top. Nothing interactive belongs there, but evals, backfills, nightly ticket classification and memory
consolidation often do.

**Self-hosting** an open model replaces per-token prices with per-hour prices. The arithmetic:
```
self-hosted $ per 1M tokens = GPU $ per hour ÷ (tokens per second × 3600 × utilization) × 1,000,000
```
Be careful which tokens you count: throughput is usually quoted for output (decode), prompt reading (prefill) is
much faster per token, and agent traffic is mostly prompt; compare against an API price blended by your
input:output ratio. Utilization is the whole story: a GPU that is busy 10% of the time costs ten times as much per token as one that is
always busy. Support traffic is spiky and mostly idle at night, which is why pay-per-token APIs usually win at
small scale, and why self-hosting pays off for steady, high-volume or data-residency-bound workloads. Elective
[E5](../../electives/E5-self-hosting/README.md) has you serve an open model on free compute tiers and measure tokens
per second yourself; feed those numbers to
`python -m agentlab.perf breakeven`.

## §7 Budgets in production
Node 02's per-run budget is a safety cap. In production, add: a per-conversation cap that degrades gracefully
(switch to the cheap model, or hand over to a person with a summary, instead of crashing); per-customer and
per-tenant rate limits (one customer's script must not spend everyone's budget); and alerts on *cost per
resolution* drifting, which catches a prompt change that made conversations longer before the monthly invoice
does.

## Key terms
cost per conversation / per resolution · blended cost · shadow price · prompt prefix · cache write premium · cache
read share · breakpoint · minimum cacheable length · cascade · escalation signal · sticky escalation · time to first
token · output tokens per second · p50/p95 · round trips · batch API · utilization
