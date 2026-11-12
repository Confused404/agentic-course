"""AGENT-OFF code under test: your agentlab/evals/stats.py."""
import math

import pytest

from agentlab.evals.stats import bootstrap_mean_ci, paired_diff_ci, pass_at_k, pass_hat_k, wilson_interval


@pytest.mark.parametrize("c,n,lo,hi", [(8, 10, 0.490, 0.943), (40, 50, 0.670, 0.888), (160, 200, 0.739, 0.849),
                                       (0, 10, 0.0, 0.278), (10, 10, 0.722, 1.0)])
def test_wilson_known_values(c, n, lo, hi):
    a, b = wilson_interval(c, n)
    assert a == pytest.approx(lo, abs=0.002) and b == pytest.approx(hi, abs=0.002)


def test_wilson_edges():
    assert wilson_interval(0, 0) == (0.0, 1.0)
    a, b = wilson_interval(5, 10, z=2.576)
    assert a < wilson_interval(5, 10)[0] and b > wilson_interval(5, 10)[1], "99% is wider than 95%"


def test_pass_at_k_and_hat_k():
    assert pass_hat_k(10, 9, 3) == pytest.approx(84 / 120)
    assert pass_at_k(10, 1, 3) == pytest.approx(1 - math.comb(9, 3) / math.comb(10, 3))
    assert pass_at_k(10, 8, 3) == 1.0, "fewer than k failures: some k-subset always contains a pass"
    assert pass_hat_k(10, 2, 3) == 0.0
    assert pass_at_k(5, 0, 1) == 0.0 and pass_hat_k(5, 5, 5) == 1.0
    assert pass_at_k(4, 2, 1) == pytest.approx(0.5) == pass_hat_k(4, 2, 1), "k=1: both equal the pass rate"
    for bad in [(3, 1, 4), (3, 4, 1), (3, 1, 0), (3, -1, 1)]:
        with pytest.raises(ValueError):
            pass_at_k(*bad)
        with pytest.raises(ValueError):
            pass_hat_k(*bad)


def test_pass_hat_k_drops_fast():
    """75% per trial -> about 42% for 3 in a row (TEXTBOOK §4)."""
    assert pass_hat_k(1000, 750, 3) == pytest.approx(0.75 ** 3, abs=0.005)


def test_bootstrap_properties():
    vals = [1.0, 1.0, 0.0, 0.5, 1.0, 0.0, 1.0, 1.0, 0.5, 1.0]
    m, lo, hi = bootstrap_mean_ci(vals, seed=1)
    assert m == pytest.approx(0.7) and lo < m < hi and 0 <= lo and hi <= 1
    assert bootstrap_mean_ci(vals, seed=1) == (m, lo, hi), "deterministic for a seed"
    _, lo2, hi2 = bootstrap_mean_ci(vals * 10, seed=1)
    assert hi2 - lo2 < hi - lo, "more tasks -> narrower interval"
    assert bootstrap_mean_ci([0.4]) == (0.4, 0.4, 0.4)
    with pytest.raises(ValueError):
        bootstrap_mean_ci([])


def test_paired_diff():
    a = {f"t{i}": 0.5 for i in range(20)}
    b = {f"t{i}": 0.5 + (0.3 if i % 2 else 0.1) for i in range(20)}
    b["only_b"] = 1.0
    d, lo, hi = paired_diff_ci(a, b)
    assert d == pytest.approx(0.2) and 0 < lo < d < hi, "a consistent improvement excludes 0"
    same = paired_diff_ci(a, dict(a))
    assert same == (0.0, 0.0, 0.0)
    noisy = {k: v + (0.3 if int(k[1:]) % 2 else -0.3) for k, v in a.items()}
    _, lo, hi = paired_diff_ci(a, noisy)
    assert lo < 0 < hi, "an up-and-down change is not shown to be different"
    with pytest.raises(ValueError):
        paired_diff_ci({"x": 1}, {"y": 1})
