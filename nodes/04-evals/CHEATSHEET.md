# Node 04 cheat sheet: evals

**Task** = input + environment + graders + tags + split · **Trial** = one fresh-environment attempt ·
**Grade** = pass / fail / unknown · capability (frontier) vs regression (must stay ~100%).

**Grader priority**: state (rows created *during* the trial) > safety/constraints > process (tool order, counts) >
reply text (facts and forbidden content only) > judge (properties code can't check).

**Judge rules**: one narrow rubric · give it evidence (tool results) · allow `unknown` · reasoning before verdict ·
different vendor from the graded model · watch position/verbosity/self-preference/leniency · calibrate on ≥ 20 human
labels incl. ≥ 8 fails: report **Cohen's κ** (≥ 0.6 usable) and **recall on failures**, not just raw agreement.
State graders on states the environment already guarantees test the environment: add process + honesty checks.

**Statistics**
- Wilson 95% for c/n. 8/10 → [49%, 94%]. 4× trials → half the width.
- Trials of a task are correlated: bootstrap over **tasks** for suite means and comparisons.
- pass@k = 1 − C(n−c,k)/C(n,k) (any of k) · **pass^k = C(c,k)/C(n,k) (all of k)**: customer-facing agents live
  here. 75% → 42% at k=3.
- Compare paired, same tasks; CI of B−A must exclude 0; distrust small deltas (infra noise ~ several points).
- Power: ~23 tasks → paired CI ≈ ±14 pts. Past 3–5 trials, add tasks, not trials.
- One pre-registered primary comparison; everything else exploratory (or Holm/Bonferroni).
- Headline = task mean + task bootstrap CI. Provider errors/timeouts are excluded (counted), not failures.

**Dataset**: 20–50 real tasks; coverage matrix; tags; ~20% held out (don't tune on it); version it; promote saturated tasks.

**CI**: Tier 1 = scripted golden/bad scripts, free, every PR, tests the *eval*. Tier 2 = live, capped, on demand,
gate only on clear regressions. Cassettes = regression snapshots, not the gate.

**Matrix**: pass rate (CI), pass^k, $/trial, **$/pass**, latency p50/p90, per tag, Pareto frontier. Pin effort/config.

**Always**: read 3 failures + 2 passes before believing a number. **Flywheel**: traces → candidates → human labels → tasks.
