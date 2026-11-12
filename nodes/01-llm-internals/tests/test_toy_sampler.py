"""AGENT-OFF code under test: your hand-written sampler (agentlab/probe/toy_sampler.py)."""
import numpy as np
import pytest

from agentlab.probe.toy_sampler import empirical_distribution, sample, softmax, top_k_filter, top_p_filter

L = np.array([2.0, 1.0, 0.5, -1.0])


def test_softmax_basics():
    p = softmax(L)
    assert p.sum() == pytest.approx(1.0) and np.all(p > 0) and np.argmax(p) == 0
    assert np.allclose(softmax(L, 1.0), np.exp(L) / np.exp(L).sum())


def test_softmax_is_numerically_stable():
    p = softmax(np.array([1000.0, 999.0]))
    assert np.all(np.isfinite(p)) and p[0] == pytest.approx(1 / (1 + np.exp(-1)))


def test_temperature_sharpens_and_flattens():
    assert softmax(L, 0.1)[0] > softmax(L, 1.0)[0] > softmax(L, 3.0)[0]
    assert softmax(L, 0.01)[0] == pytest.approx(1.0, abs=1e-6)


def test_top_k():
    p = softmax(L)
    k2 = top_k_filter(p, 2)
    assert np.count_nonzero(k2) == 2 and k2.sum() == pytest.approx(1.0) and k2[0] > 0 and k2[1] > 0
    assert np.allclose(top_k_filter(p, 10), p)


def test_top_p_keeps_smallest_sufficient_set():
    p = np.array([0.5, 0.3, 0.15, 0.05])
    assert np.count_nonzero(top_p_filter(p, 0.5)) == 1
    assert np.count_nonzero(top_p_filter(p, 0.75)) == 2
    assert np.count_nonzero(top_p_filter(p, 0.81)) == 3
    assert np.allclose(top_p_filter(p, 1.0), p)
    assert top_p_filter(p, 0.0).sum() == pytest.approx(1.0) and np.count_nonzero(top_p_filter(p, 0.0)) == 1
    out = top_p_filter(np.array([0.05, 0.5, 0.15, 0.3]), 0.75)   # unsorted input
    assert np.count_nonzero(out) == 2 and out[1] > 0 and out[3] > 0


def test_greedy_and_seeded_sampling():
    assert all(sample(L, temperature=0) == 0 for _ in range(20))
    a = [sample(L, 1.0, rng=np.random.default_rng(5)) for _ in range(3)]
    b = [sample(L, 1.0, rng=np.random.default_rng(5)) for _ in range(3)]
    assert a == b


def test_empirical_matches_theory():
    f = empirical_distribution(L, 20000, rng=np.random.default_rng(0), temperature=1.0)
    assert np.allclose(f, softmax(L), atol=0.015)
    g = empirical_distribution(L, 5000, rng=np.random.default_rng(0), temperature=1.0, top_k=1)
    assert g[0] == 1.0
