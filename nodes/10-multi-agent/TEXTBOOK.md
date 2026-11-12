# Node 10 TEXTBOOK: Multi-agent systems: when one context isn't enough, and what a second one costs

> Vendor-neutral. Product names and dated facts live in `APPENDIX-2026-11.md`.

## Learning objectives
By the end you can:
1. Say what a multi-agent system buys (more total context, parallel wall time, isolation) and what it costs
   (tokens, coordination, lost information), and predict which side wins for a given task.
2. Build orchestrator–worker delegation where each worker gets a **self-contained brief**, a **fresh context** and
   **tools scoped to its shard**, and runs in parallel.
3. Write the merge step so it never silently loses a shard, invents data, or picks a winner between conflicting
   reports.
4. Compare a single agent, an orchestrator and a fixed map-reduce workflow on the same tasks, on correctness,
   tokens, peak context, wall time and failure modes.
5. Recognize the common multi-agent failure modes in a transcript and trace each to a design decision.

---

## §1 What "multi-agent" means here

An **agent** is a model using tools in a loop (Node 02). A **multi-agent system** is several such loops whose
inputs and outputs are wired together. Strip away the branding and there are only a few shapes:

| Shape | Who decides the split | Contexts | Example |
|---|---|---|---|
| **Single agent** | the model, inside one loop | one, growing | Node 02–06 support agent |
| **Workflow with LLM steps** | your code | one per step, fresh | Node 09 cascade; map-reduce here |
| **Orchestrator–workers** | a lead model, at run time | lead + one per worker | coding agents' "subagents", deep research |
| **Handoff** | the current agent passes control | one at a time | triage bot hands a ticket to a billing agent |
| **Peer teams** | agents message each other | many, long-lived | experimental "agent teams" |

This node measures the first three on the same tasks. Handoffs are a routing decision (Node 09 thinking applies);
peer teams add the hardest problems of all (shared state between writers) and are mentioned, not built.

---

## §2 Why more agents can help

Three mechanisms, and only three:

1. **More total context.** One context window holds what one agent can attend to at once. Ten workers can each read
   a different tenth of a large corpus. The lead receives *compressed* results: the workers do the reading, and only
   their conclusions travel. In one published analysis of a research orchestrator, **how many tokens were spent**
   explained most of the variance in performance on a browsing benchmark (APPENDIX): multiple agents are largely a
   way to spend more tokens productively, not a source of cleverer reasoning.
2. **Parallel wall time.** Independent workers run at the same time: wall time ≈ the slowest worker, not the sum.
3. **Isolation.** A worker's mess (dead ends, raw tool output, an injection in a review) stays in its context. The
   lead sees a report. That's also a security property (Node 08): a worker that reads untrusted text and has no
   write tools can be steered only into a wrong report, never into a wrong action.

And one non-mechanism: "specialist personas" ("you are the pricing expert") rarely help by themselves. A worker is
better than the single agent only if it has *different context or different tools*, not a different job title.

---

## §3 Why more agents usually hurt

- **Tokens.** Every worker pays for its own system prompt, tool definitions and brief, plus its own tool results;
  the lead pays again to read the reports. Published figures: agents use several times the tokens of a chat, and
  multi-agent systems several times more again (APPENDIX). If the single agent already succeeds, that multiple is
  pure cost.
- **Lost context.** A worker knows only its brief. Everything the lead understood but didn't write down is gone:
  the definition of "average rating", the threshold, the output shape, *why* the work matters. Coding-agent
  builders put this as two principles: **share context**, and **actions carry implicit decisions**: parallel
  workers that each make silent choices (a style, an edge case, a rounding rule) produce parts that don't fit.
- **The merge.** Results must be combined. Missing shards, duplicated items, conflicting values, and partial
  results that *can't* be combined (an average of averages) are all merge failures, and they're silent unless you
  make them loud (§5).
- **Coordination failures.** The lead re-does work a worker did, delegates the same shard twice, stops before every
  shard reports, or "verifies" by asking the same worker again. A failure taxonomy built from over a thousand
  annotated multi-agent traces groups these into three families: *specification* problems (bad briefs, wrong roles),
  *inter-agent misalignment* (ignored or lost information), and *verification* failures (stopping early, not
  checking). The authors found most of them were system-design problems, not just model limitations.
- **Debuggability.** One transcript becomes seven. Without per-agent traces (Node 02 spans; `show` here), you can't
  tell which agent was wrong.

**The rule of thumb:** use more agents only when the task is **breadth-heavy** (many independent pieces), the pieces
are **read-mostly** (workers gather, one agent decides and writes), the single agent is **demonstrably failing**
(context overflow, missed items, too slow), and the value of the answer pays for the tokens. Writes stay
single-threaded.

---

## §4 Delegation: the brief is the interface

A worker is a function whose only argument is a string. Write it like an API contract:

```
Objective   What to find, for which shard, and why (one line of purpose prevents a lot of wrong guesses).
Definitions Every term with a precise meaning: "average rating = mean of all review ratings, rounded to 2 dp,
            only products with ≥ 10 reviews"; the time window; the tie-break.
Scope       Exactly which shard; what NOT to do ("don't read reviews; ratings are in product_stats").
Output      The exact shape of report.items: keys and fields. Ask for fields that COMBINE across shards
            (counts and sums, not only averages; raw values, not only the top 1).
Effort      Rough size: "6 products, one product_stats call" stops a worker from wandering.
```

Then make the system enforce what the brief can't:
- **Scoped tools.** A worker's tools only see its shard, and the error says what it *can* query (Node 05: errors
  are instructions). This stops wandering, and makes "unexpected shard" reports impossible by construction.
- **A report tool with a schema**, called once. Free-text answers from workers are the most common merge failure.
- **Bounded fan-out.** A cap on workers per delegation and on delegations per run, enforced in the tool.
- **Parallel by default** for independent shards; the lead's prompt should say so, and the tool should run them
  concurrently whatever order the model lists them in.

The orchestrator in this node can't query data itself: it can only list shards, delegate and answer. That forces
the architecture you're measuring. Real systems often let the lead do small lookups itself; YOU_DO task 6 asks what
that changes.

---

## §5 Reconciling: the merge is where work disappears

The merge takes N reports and must be **honest**. Your `reconcile()` (AGENT-OFF) encodes the rules:

| Situation | Silent (wrong) behaviour | Honest behaviour |
|---|---|---|
| A shard never reported | merged result just lacks it | listed in `missing_shards`; lead re-delegates or says so |
| A worker crashed | exception kills the run, or it's ignored | an `ok=False` report → missing |
| A retry succeeded | both attempts merged | the shard's **last** report replaces earlier ones |
| Two shards report the same key, same value | double-counted | kept once, listed as a duplicate |
| Two shards disagree | last writer wins | **conflict**: withheld from the merge, surfaced with both values |
| A worker reported a shard it wasn't given | merged as if valid | `unexpected`: not evidence |

Two further rules aren't in `reconcile()` but in the architecture:
- **Combinability.** An average of averages is not the average over all reviews: products (and categories) have
  different review counts. If a worker averages its products' averages, or reports only averages, no merge can
  recover the right answer. Ask for sums and counts (the `rating_sum` field exists for this). In this node's data
  the error is small (a few hundredths), which is exactly why it survives eyeballing; the grader's ±0.01 catches it.
- **Coverage before answering.** The lead's `delegate` result includes `not_yet_covered`. An answer given while
  shards are missing must say so; in the evals it's graded wrong even when it happens to match the gold answer.

---

## §6 Measuring architectures

Correctness first, then what it cost. For each architecture on the same tasks:

| Metric | Why |
|---|---|
| accuracy vs SQL gold | exact grading: no judge needed (Node 04) |
| tokens per task (and × vs single) | the main cost; multi-agent's price of admission |
| tokens by role (lead / worker / reducer) | where the tokens went; is the lead re-reading everything? |
| **peak prompt** | the largest single prompt any agent sent: what context isolation is meant to shrink |
| wall time (p50) | what parallelism is meant to buy |
| agents, calls | coordination overhead |
| runs with missing shards, conflicts | merge health |

Read the per-task table, not just the average: architectures fail on *different* tasks. A single agent fails on
breadth when the data outgrows what it can track (skipped categories, lost items after many tool results); here the
catalogue is small (a single agent's largest prompt is a few thousand tokens), so expect it to do well, and treat
that as a finding, not a flaw. An orchestrator fails on briefs (an undefined term, an uncombinable output); a fixed
workflow fails when the question doesn't fit its fixed split.

Two accounting details make the multiple look worse than the architecture deserves, and you should know them: every
worker spends one extra call after it reports (the loop asks the model once more and it says "done"), and parallel
workers can overshoot a budget cap by up to one call each, because all of them pass the check before any of them is
charged.

With five tasks and one trial each, you're looking at anecdotes: run `--trials 3` on the tasks that differ before
concluding anything (Node 04: variance is real).

---

## §7 The fixed workflow alternative

If the split is known in advance (here: by category), **code can do the orchestration**: shard, run workers with a
fixed brief in parallel, retry missing shards once (a line of code, not a judgment call), and have one reducer call
combine. It's cheaper (no lead loop), more predictable, and easier to debug, but it can't adapt: a question whose
natural split is different (by month, by customer) needs a different workflow. This is Node 09's lesson again:
**use the least autonomy that does the job.** An orchestrator earns its keep when the split itself must be
discovered at run time.

And the cheapest "multi-agent system" of all is often **a better tool**: these tasks are one SQL query each. A
coarse `category_summary` tool would make the single agent fast and right (YOU_DO task 6). When a tool can do the
aggregation, more agents are solving the wrong problem.

---

## Design trade-offs

| Decision | Option A | Option B | Choose by |
|---|---|---|---|
| Who splits the work | code (workflow) | a lead model | is the split known in advance? |
| Worker context | brief only | brief + lead's full trace | read-only gathering → brief; workers making decisions → share more, or don't parallelize |
| What workers return | conclusions | raw facts | can the conclusions be combined correctly? |
| Merge | code (`reconcile`) | the lead reads everything | code for structure (missing, conflicts); model for judgment |
| Lead can query data | no | yes | forcing delegation vs letting the lead check a worker |
| Workers write | never | with approval | default never: writes stay single-threaded |

## Common failure modes and debugging

| Symptom | Likely cause | Fix |
|---|---|---|
| Right answer for 5 categories, 6th missing | a worker never reported; lead didn't check coverage | `not_yet_covered` in the result; prompt rule; re-delegate |
| Category averages slightly off | average of averages | ask for `rating_sum` and `reviews`; pool in the lead |
| Worker used a different threshold | the brief didn't state it | definitions section in every brief |
| Lead's prompt huge after delegation | workers returned raw data for everything | ask workers for only what the answer needs |
| Orchestrator slower than single | workers ran sequentially, or one worker looped | check the pool; cap worker turns |
| Many tokens, same accuracy as single | the task wasn't breadth-heavy for this model | don't use multi-agent here |
| Workers' reports disagree | different rounding or definitions | conflicts surface in `reconcile`; fix the brief |

## Self-check
1. Name the three mechanisms by which multiple agents help. Which of them would a single agent with a
   1M-token context also get?
2. A worker returns `{"avg_rating": 3.91}` for its category. Why can't the lead compute the store-wide average
   from six of these? What should the brief have asked for?
3. Your `reconcile` receives two reports for "kitchen": the first ok, the second `ok=False`. What's missing, and why
   is "last report wins" the right rule here?
4. Why are conflicting keys withheld from `merged` instead of resolved by order?
5. When is a fixed map-reduce workflow better than an orchestrator? Give a task where it would be worse.
6. A worker reads customer reviews that contain an injection. What's the worst it can do in this node's design,
   and which design decisions bound that?
7. The orchestrator used 6× the tokens of the single agent and both got 5/5. What do you ship?

<details><summary>Answers</summary>

1. More total context, parallel wall time, isolation. A 1M-token single agent gets the capacity part of "more
   context" but not the compression (it still attends over everything at once, and long contexts degrade: Node 06),
   not the parallelism, and not the isolation.
2. Averages don't combine: categories (and products) have different review counts, so the overall mean is a
   weighted mean. The brief should ask for `rating_sum` and `reviews`, which add up exactly.
3. Kitchen is missing. The second report is the newer word on that shard (a retry that failed, or a worker
   retracting a bad result); merging the older one would treat superseded data as current. The honest outcome is
   "missing", so the lead re-delegates.
4. Order is an accident of scheduling (which thread finished last), not evidence. Picking by order hides the
   disagreement; withholding it forces someone to look, and usually reveals a brief that left a definition open.
5. When the split is known in advance and the same for every question (per category, per month): it's cheaper,
   deterministic and debuggable. Worse when the right split depends on the question: "which customers bought from
   three or more categories?" needs a split by customer, not by category.
6. Produce a wrong report for its shard (e.g. claim a product's stats are different). It can't send email, refund or
   write anything: workers have read-only tools scoped to one shard, and the lead only sees a structured report.
   Bounded by: no write tools, scoped tools, schema'd report, and conflicts surfacing in `reconcile`.
7. The single agent. Same accuracy at a sixth of the tokens; revisit if the catalogue grows until the single agent
   starts missing items or takes too long, and measure again.
</details>

## Socratic review prompt
> I built a multi-agent system: [paste your ADR 0007 draft and the report table]. Act as a skeptical staff
> engineer. Ask me one question at a time about whether the extra agents are justified: what the single agent
> failed on, whether a better tool would fix that, how missing shards and conflicts are handled, and what the
> token multiple buys. Don't accept "it's more scalable" without a number.
