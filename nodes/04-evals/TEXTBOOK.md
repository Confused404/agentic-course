# Node 04 Textbook: Evals in depth

> You can't improve what you can't measure, and with LLM systems you can't measure with one run. This node
> turns Node 02's smoke detector into a measurement instrument: isolated trials, layered graders, honest
> statistics, two CI tiers, cross-model comparisons, and a loop that turns production failures into new tests.
> From here on, every claim you make about your agents ("the new prompt is better", "Model B is good enough")
> should come with a number and an error bar.

## Learning objectives
1. Design an eval task, trial and grader stack, and explain why outcome grading beats transcript grading.
2. Build and *validate* an LLM judge (rubric, "unknown" option, agreement with your own labels, known biases).
3. Compute and interpret pass rates with confidence intervals, **pass@k** and **pass^k**, and decide which one a
   product needs.
4. Compare two systems correctly (paired, on the same tasks) and know when a difference is noise.
5. Run evals in two CI tiers (deterministic and live) without flakiness or runaway cost.
6. Grow an eval set from real failures (the data flywheel) and keep a held-out set honest.

---

## §1 What evals are for

A **test** checks deterministic behaviour: same input, same output, pass or fail forever. An **eval** measures
the behaviour of a *stochastic* system on a *distribution* of tasks. You get a rate, not a verdict, and the
rate has uncertainty.

Two kinds, with different jobs:

| | Capability evals | Regression evals |
|---|---|---|
| Question | "Can it do this yet? How well?" | "Did we break something that used to work?" |
| Expected pass rate | low-to-medium (it's a frontier) | high (~100%) |
| When a task starts passing reliably | it graduates into the regression set | stays |
| Use | choosing models, prioritising work | gating merges and releases |

What to measure, in order of importance for an agent that acts:
1. **Outcome**: did the world end up in the right state (refund row, ticket, order status)?
2. **Safety/constraints**: did it avoid what it must never do (refund the wrong customer, leak data)?
3. **Process**: did it take a reasonable path (checked eligibility before refunding; didn't call 14 tools)?
4. **Communication**: is the reply correct, honest, clear, polite?
5. **Cost and latency** per task, and per *successful* task.

---

## §2 Anatomy: task, trial, transcript, grade

```
TASK      = input (customer id + messages or a simulated user) + environment setup + graders + tags
TRIAL     = one attempt at a task: fresh environment → run agent → transcript + final state
GRADERS   = functions of (final state, transcript, reply) → pass / fail / unknown (+ detail)
METRICS   = aggregates over trials and tasks (rates, intervals, pass^k, cost)
```

**Isolation.** Every trial gets a fresh copy of the database, a fixed clock and its own budget. A trial
must not be able to affect another: shared state is the most common source of "flaky" evals that are
actually *wrong*.

**Infrastructure noise.** Scores move for reasons unrelated to the agent: rate limits and retries, timeouts
that are too tight, a laptop under load, a provider having a slow hour. Anthropic reported that varying only the
container resources of an agentic coding benchmark moved scores by about 6 points. Their recommendations, which
the course adopts:
- pin resources (timeouts, memory) and keep a separate, generous **kill ceiling** so a slow trial is
  recorded as slow, not as failed;
- run several trials, ideally spread over time;
- treat differences of a few points as noise until proven otherwise (§4).

**Determinism where you can get it.** You can't make the model deterministic (Node 01 §4), but everything else
can be: seeded data, fixed clock, scripted user turns or seeded simulated users, pinned tool behaviour.

---

## §3 Graders: code first, models when you must

### Code-based graders
Fast, free and deterministic. Prefer them whenever the property is checkable:
- **State** graders query the environment: refund rows created during the trial, escalation tickets, order status,
  emails in the outbox. These are the gold standard for agents that act. One trap: a state grader on a state the
  environment *already guarantees* tests the environment, not the agent. Shopfront's service layer blocks
  out-of-policy refunds, so "no refund for 4832" passes even for an agent that tried to refund it and then told the
  customer "Done, refunded!". Pair such graders with process and honesty checks (`tools_not_called: issue_refund`,
  a `reply_not_regex` for false refund claims).
- **Process** graders read the tool calls: `tools_called`, `tools_not_called`, `tool_order` (eligibility before
  refund), `max_tool_calls` (efficiency).
- **Reply** graders: `contains_any`, `not_contains`, regex. Brittle, so use them for hard facts (an amount, a
  window length) and for forbidden content (another customer's data), not for style.

### Model-based graders (LLM-as-judge)
For properties code can't check: "did it explain *why* the refund was refused, correctly?", "was it honest
that the refund is pending, not done?", "was the tone appropriate for an angry customer?"

A judge is itself a model you must evaluate. The rules:
1. **One narrow rubric per judge.** "Rate the reply 1–10" measures nothing reliably. "Does the reply state that
   the refund needs human approval and NOT that it has been issued? pass / fail / unknown" can be checked.
2. **Give it the evidence**: the conversation, the relevant tool results, and the policy facts. Don't make it
   guess what's true.
3. **Allow "unknown".** Forcing a binary verdict on an ambiguous case produces confident noise. Count unknowns
   separately and read them; they usually mean the rubric or the task is unclear.
4. **Ask for a short justification *before* the verdict** in a structured output (Node 01 §4: field order matters).
5. **Use a different model (ideally a different vendor) from the one being graded.** Models prefer outputs like
   their own (self-preference), and preference training makes them lenient (Node 01 §5).
6. **Know the biases**: position bias in pairwise comparisons (swap the order and average), verbosity bias (longer
   looks better), leniency, sensitivity to confident tone.
7. **Validate before trusting.** Hand-label 20–30 transcripts yourself (include at least ~8 that you think
   *fail*), run the judge on them, and measure:
   - **raw agreement**: misleading alone, because if 90% of cases pass, an always-pass judge agrees 90% of the time;
   - **Cohen's κ** = (p_o − p_e)/(1 − p_e), agreement corrected for chance (p_e from each rater's pass/fail rates).
     Above ~0.6 is usable; above ~0.8 is good;
   - **recall on failures**: of the cases *you* failed, how many did the judge fail? That's what the judge exists for.
   And remember that 18/20 agreement has a Wilson interval of about [70%, 97%]: twenty labels can't certify a judge,
   only catch a bad one. Fix the rubric before using a judge that disagrees with you systematically.

### Humans
The final reference. Use them to label the calibration set for judges, to review failures, and to spot-check
passes, because graders have bugs too.

### Combining graders
A task passes when **all** its required graders pass. A grader returning `unknown` makes the trial `unknown`,
which is reported separately and excluded from the pass rate (with the exclusion count shown). Partial credit
(weighted scores) is useful for capability tracking but hides failures in a regression gate.

---

## §4 Statistics: what a pass rate means

### One rate, honest uncertainty
`c` passes out of `n` trials estimates the pass probability `p`. Its 95% interval is **not** `p ± 1.96·sqrt(p(1-p)/n)`
(the "Wald" interval, which collapses to zero width at 0% or 100% and misbehaves at small n). Use the **Wilson**
interval:

```
center = (p̂ + z²/2n) / (1 + z²/n)
half   = z · sqrt( p̂(1-p̂)/n + z²/4n² ) / (1 + z²/n)        z = 1.96 for 95%
```
8/10 → [0.49, 0.94]. 40/50 → [0.67, 0.89]. 160/200 → [0.74, 0.85]. To halve the interval you need about 4×
the trials.

### Tasks are not coin flips from one coin
Each task has its own pass probability. Some your agent always passes, some never, some ~50%. Two consequences:
- Trials of the *same* task are correlated. 10 tasks × 10 trials is **not** 100 independent samples. For an
  honest interval on the suite's mean, use a **bootstrap over tasks** (resample tasks with replacement, recompute
  the mean, take percentiles).
- Report per-task rates. The suite average hides the 0% task that is your next bug.

### pass@k vs pass^k
Run each task `k` times:
- **pass@k**: the probability that **at least one** of k attempts succeeds: `1 − (1−p)^k`. That's right when
  a human or a verifier picks the best attempt (code generation with tests).
- **pass^k** ("pass-hat-k"): the probability that **all** k attempts succeed: `p^k`. That's right when every
  attempt reaches a customer. A support agent that's right 75% of the time handles 3 customers in a row correctly
  only 0.75³ ≈ **42%** of the time.

From `n` trials with `c` passes, the unbiased estimators are
```
pass@k = 1 − C(n−c, k) / C(n, k)          pass^k = C(c, k) / C(n, k)
```
computed per task, then averaged over tasks. For customer-facing agents, **pass^k is the number that matters**,
and it drops off quickly.

### Comparing two systems
"Prompt B scored 78%, prompt A 74%" means nothing on its own. Do it properly:
1. **Same tasks, same trial count, same environment**, interleaved in time if you can (provider noise).
2. **Paired** analysis: per task, compute the rate difference B − A, then bootstrap over tasks for a CI of the
   mean difference. If the CI includes 0, you haven't shown a difference.
3. Be sceptical of small deltas (a few points) even when "significant": infrastructure noise (§2) can produce them.
4. Decide your metric and threshold **before** looking (otherwise you'll find the comparison that favours your
   change).

### How small a difference can you see? (power)
With ~23 tasks whose per-task difference has a standard deviation around 0.35, the standard error of the mean
difference is ≈ 0.35/√23 ≈ 0.07, so a 95% interval is about **±14 points**. Differences under ~15 points are
invisible to a suite this size, however many trials you run. "Four times the trials halves the interval" holds for a
single pooled rate, but at the suite level the interval is floored by **between-task** variation. Beyond ~3–5 trials
per task, add *tasks*, not trials. (With ~20 tasks, the simple percentile bootstrap also under-covers a bit; a sign or
permutation test on per-task differences is a good second opinion.)

### Many comparisons
Three models give three pairwise comparisons. Twenty tags give twenty slices. Look at enough slices and one will
"significantly" differ by chance (forking paths). Discipline:
- **pre-register one primary comparison** (the decision you're actually making) and its metric;
- treat everything else (other pairs, per-tag tables) as **exploratory**: hypotheses for the next run, not
  conclusions. If you must test several, adjust (Holm or Bonferroni: with 3 comparisons, require p < 0.05/3 for the
  smallest);
- small slices (one task × three trials) are anecdotes. The report shows counts, not just percentages, for that reason.

---

## §5 Building the dataset

Start with **20–50 tasks drawn from real or realistic failures**, not hundreds of synthetic ones. Sources:
1. **Specs and policies**: each rule → at least one task on each side of it (the boundary fixtures 4831–4834).
2. **Known failures**: every bug you fixed becomes a regression task.
3. **Production traces** (§10): escalations, complaints, tool errors, long conversations.
4. **Adversarial**: social engineering, ambiguity, multi-intent, other languages, injections (Node 08).

Keep a **coverage matrix** (behaviour × difficulty × tag) to see gaps. Tag tasks (`refund`, `boundary`,
`privacy`, `multi-turn`…) so you can report by slice.

**Held-out set.** Mark ~20% of tasks `split: heldout` and *don't look at their results while iterating*.
When you tune prompts against the dev split for long enough, you overfit it, and the held-out score
tells you how much (Node 05). Two honest caveats about this suite's held-out split: with 7 tasks it can only detect
*gross* overfitting (see power, §4), and two held-out tasks share fixtures and rules with dev tasks (4832, 4826), so
some "generalisation" is near-duplication. Real held-out sets need more tasks and fixtures used in only one split.

**Version the suite.** A score is meaningless without the suite version it was measured on.

**Saturation.** When the regression set is ~100% for every model you care about, it no longer discriminates.
Promote harder capability tasks.

---

## §6 Simulated users

Scripted turns ("Yes, go ahead") are deterministic but rigid: the agent's second question may not be the one
the script answers. A **simulated user** is a model playing the customer, given:
- a **persona** (impatient, vague, non-native speaker),
- a **goal** and **private facts** it reveals only when asked ("the item arrived broken; you have a photo"),
- a **stop rule** (say `[DONE]` when the goal is met or clearly refused).

Risks: simulated users are too cooperative, too articulate, and drift off-script. Mitigations: specific facts and
constraints in the persona, a cheap model at low effort, a turn cap, and grading the *agent's* outcome, never the
simulator's satisfaction. Treat simulated-user tasks as a separate slice, because they add variance of their own.

---

## §7 Evals in CI: two tiers

| | Tier 1: every PR | Tier 2: on demand / nightly |
|---|---|---|
| Model | **scripted fake** (golden scripts per task) | real models |
| Tests | the harness, graders and environment; that each task is *satisfiable* and its graders *discriminate* | the agent's quality |
| Cost | free | capped (`--budget`) |
| Flakiness | none (deterministic) | expected: thresholds use intervals |
| Gate | hard fail | fail only on clear regressions (CI upper bound below threshold, or paired diff CI entirely below 0) |

Why not record real responses and replay them ("cassettes")? A cassette is valid only for the exact prompt it
was recorded with. Edit the system prompt and every cassette is stale. They're useful as **regression
snapshots** of known-good transcripts, not as the main gate.

Tier 1 has a second job people forget: **testing the eval itself.** For each task you write a *golden script*
(what a correct agent would do) that must pass, and for important tasks a *bad script* that must fail. An eval
whose graders pass a lying agent (Node 02's "Done! Refunded" with no tool call) is worse than no eval.

Secrets: Tier 2 needs API keys as CI secrets, which GitHub withholds from PRs opened from forks. Trigger Tier 2 by
label or manually.

---

## §8 The cross-model matrix

Run the same suite on several models (the course default: `fast`, `gpt-fast`, `local`) with the same trial count,
and report per model: pass rate (CI), pass^k, cost per trial, **cost per successful task**, latency p50/p90, and
per-tag pass rates. Then look at the **Pareto frontier**: the models that no other model beats on both quality and
cost. Everything else is dominated.

Pin and report configuration (effort, max tokens, prompt version). "Model A beats Model B" without the
configuration is a comparison of configurations you didn't write down (Node 01 §6).

---

## §9 Read the transcripts

Scores tell you *that* something failed; transcripts tell you *why*, and whether it really failed. Before trusting
any new eval result, read a sample of failures **and** a sample of passes. You will regularly find:
- **grader bugs** (the reply said "thirty days", the grader looked for "30"),
- **task bugs** (the expected outcome is wrong, or the task is ambiguous),
- **environment bugs** (timeouts, missing data),
- and real agent failures, which you classify (Node 02: selection / arguments / interpretation / environment).

A useful habit: every eval report ends with three hand-read failures and what each one taught you.

---

## §10 The data flywheel

```
production traces ──▶ candidate cases (errors, escalations, long or expensive conversations, low ratings)
       ▲                     │ triage: real bug? duplicate? ambiguous?
       │                     ▼
  improved agent  ◀── labeled eval tasks (expected outcome written by a human) ── regression set
```
Automate the first arrow (mine traces for signals), keep a human on the second (labelling the expected outcome),
and the suite grows exactly where your agent fails in reality. Without this loop, eval sets fossilise around the
problems you imagined on day one.

---

## Design trade-offs

| Decision | Options | Course choice |
|---|---|---|
| Primary signal | reply text / transcript / final state | state, then process, then reply |
| Judge verdicts | 1–10 score / binary / binary + unknown | binary + unknown, justification first |
| Uncertainty | none / Wald / Wilson / bootstrap over tasks | Wilson per rate; task bootstrap for suite means and paired diffs |
| Reliability metric | pass@k / pass^k | pass^k for customer-facing agents |
| CI gate | live evals on every PR / scripted + live on demand | scripted Tier 1 always; live Tier 2 on demand/nightly |
| Dataset | big synthetic / small real | small, real, growing via the flywheel |

## Common failure modes and debugging

| Symptom | Likely cause | Check |
|---|---|---|
| Score changes run to run with no code change | sampling noise, infra noise, shared state | trial count, CIs, fresh env per trial, timeouts |
| A task passes for an agent that did nothing | grader checks a pre-existing state | graders must look at changes *during* the trial; write a bad script |
| Judge passes everything | leniency, rubric too vague, judge = generator | calibration set; narrower rubric; different vendor |
| Judge says unknown a lot | ambiguous task or missing evidence | give the judge tool results and policy facts; fix the task |
| Prompt change "improves" dev, not held-out | overfitting the dev set | held-out split; fewer, more principled changes |
| Model A beats B on the suite, loses in production | suite doesn't match traffic | flywheel; tag slices by real frequency |
| Eval run costs 10× estimate | simulated users chatting, reasoning tokens, no caps | per-trial budget, turn caps, effort pinned |

## Self-check
1. Your support agent passes a task in 9 of 10 trials. What's its pass^3 estimate (unbiased), and what's the naive
   p̂³? Why might they differ?
2. You have 12 tasks × 5 trials = 60 trials, 48 passes. Why is the Wilson interval on 48/60 too narrow for the suite?
3. A judge model agrees with your labels 78% of the time on a binary rubric. Ship it?
4. Prompt B beats prompt A by 3 points on 30 tasks × 3 trials. What would convince you it's real?
5. Why do golden scripts and bad scripts in Tier 1 test the *eval*, not the agent?
6. Which tasks belong in the held-out split, and what are you not allowed to do with them?
7. Your 23-task suite shows model B 6 points above model A, paired CI [−8, +20]. Your manager asks for 10 trials per
   task instead of 3 to "make it significant". Will that work?

<details><summary>Answers</summary>

1. Unbiased: C(9,3)/C(10,3) = 84/120 = 0.70. Naive: 0.9³ = 0.729. The estimator accounts for drawing 3 *distinct*
   trials from 10; with few trials the naive plug-in is biased upward.
2. Trials within a task are correlated (each task has its own p), so the effective sample size is closer to the
   number of tasks than the number of trials. Bootstrap over the 12 tasks for an honest interval.
3. No. Inspect the disagreements: is the rubric ambiguous, is the evidence missing, is the judge biased (lenient? fooled
   by confident language?). Fix and re-measure; aim for ≥85–90%.
4. A paired bootstrap over tasks whose 95% CI for B−A excludes 0, a re-run at a different time that reproduces the
   effect, more trials if the CI is wide, and failures read on both sides to see *what* changed.
5. They run with a scripted model whose behaviour you control: a correct script must pass and an incorrect one must
   fail. If not, the task or grader is broken. The agent's quality isn't involved at all.
6. A representative ~20% sample, chosen before you start iterating. You may run them only for checkpoint
   decisions (e.g. at the end of Node 05), never to guide individual changes. Once you've tuned against them,
   they're dev tasks.
7. Mostly no. Extra trials shrink the within-task noise, but the interval is dominated by the variation of the B−A
   difference *between tasks*. To detect ~6 points you need many more tasks (roughly 4× the tasks to halve the
   interval), or tasks targeted at where A and B differ.
</details>

## Socratic review prompt
> Read nodes/04-evals/TEXTBOOK.md and my latest eval report under runs/evals/. Don't write code. Ask me 6 questions,
> one at a time, that test whether I can interpret it: intervals, pass^k vs pass@k, whether a model difference is
> real, what the unknowns mean, and which failure I should look at first. Challenge any conclusion I state without
> an interval.
