"""AGENT-OFF: eval statistics. You write these by hand (Node 04 YOU_DO task 2). Standard library only.

Read TEXTBOOK §4 first. Tests: nodes/04-evals/tests/test_stats.py.

wilson_interval(passes, n, z=1.96) -> (lo, hi)
    Wilson score interval for a binomial proportion. n == 0 -> (0.0, 1.0). Clamp to [0, 1].
pass_at_k(n, c, k) -> float
    Unbiased estimate of P(at least one of k attempts passes) from n trials with c passes:
    1 - C(n-c, k) / C(n, k). If n - c < k the answer is 1.0. Raise ValueError if k < 1 or k > n or not 0 <= c <= n.
pass_hat_k(n, c, k) -> float
    Unbiased estimate of P(all k attempts pass): C(c, k) / C(n, k) (0.0 if c < k). Same validation.
bootstrap_mean_ci(values, iters=2000, alpha=0.05, seed=0) -> (mean, lo, hi)
    values are per-TASK numbers (e.g. per-task pass rates). mean = plain mean of values. Resample len(values) values
    with replacement `iters` times using random.Random(seed); lo/hi are the alpha/2 and 1-alpha/2 percentiles of the
    resampled means (sort them; lo = sorted[int(alpha/2 * iters)], hi = sorted[int((1 - alpha/2) * iters) - 1]).
    Empty values -> ValueError. One value -> (v, v, v).
paired_diff_ci(a, b, iters=2000, alpha=0.05, seed=0) -> (mean_diff, lo, hi)
    a, b: {task_id: rate}. Use only task ids present in BOTH (ValueError if none). Per task d = b - a, then
    bootstrap_mean_ci over the d values with the same iters/alpha/seed.
"""
from __future__ import annotations


def wilson_interval(passes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    raise NotImplementedError("AGENT-OFF: implement by hand (Node 04 YOU_DO task 2)")


def pass_at_k(n: int, c: int, k: int) -> float:
    raise NotImplementedError("AGENT-OFF")


def pass_hat_k(n: int, c: int, k: int) -> float:
    raise NotImplementedError("AGENT-OFF")


def bootstrap_mean_ci(values: list[float], iters: int = 2000, alpha: float = 0.05,
                      seed: int = 0) -> tuple[float, float, float]:
    raise NotImplementedError("AGENT-OFF")


def paired_diff_ci(a: dict[str, float], b: dict[str, float], iters: int = 2000, alpha: float = 0.05,
                   seed: int = 0) -> tuple[float, float, float]:
    raise NotImplementedError("AGENT-OFF")
