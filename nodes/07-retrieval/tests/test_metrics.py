"""AGENT-OFF: metrics.py (YOU_DO task 3). Work each expected value out on paper first."""
import math

import pytest

from agentlab.retrieval.metrics import hit_at_k, ndcg_at_k, recall_at_k, reciprocal_rank, rrf_fuse

R = ["a", "x", "a", "b", "y", "c"]          # duplicates: 'a' counts once, at rank 1 -> deduped a, x, b, y, c


def test_recall_and_hit():
    assert recall_at_k(R, {"a", "b"}, 2) == 0.5
    assert recall_at_k(R, {"a", "b"}, 3) == 1.0, "dedupe before cutting at k"
    assert recall_at_k(R, {"z"}, 5) == 0.0
    assert hit_at_k(R, {"c", "z"}, 5) == 1.0 and hit_at_k(R, {"c"}, 4) == 0.0
    assert recall_at_k(R, set(), 5) is None and hit_at_k(R, set(), 5) is None


def test_reciprocal_rank():
    assert reciprocal_rank(R, {"b"}) == pytest.approx(1 / 3)
    assert reciprocal_rank(R, {"b", "a"}) == 1.0
    assert reciprocal_rank(R, {"q"}) == 0.0 and reciprocal_rank(R, set()) is None


def test_ndcg():
    assert ndcg_at_k(["a", "b"], {"a", "b"}, 2) == pytest.approx(1.0)
    assert ndcg_at_k(["x", "a"], {"a"}, 2) == pytest.approx(1 / math.log2(3))
    # gold {a, b}; ranking x, a, y, b at k=4: DCG = 1/log2(3) + 1/log2(5); IDCG = 1 + 1/log2(3)
    exp = (1 / math.log2(3) + 1 / math.log2(5)) / (1 + 1 / math.log2(3))
    assert ndcg_at_k(["x", "a", "y", "b"], {"a", "b"}, 4) == pytest.approx(exp)
    assert ndcg_at_k(["x", "a", "a"], {"a"}, 3) == pytest.approx(1 / math.log2(3)), "duplicates count once"
    # more gold than k: IDCG uses min(|gold|, k)
    assert ndcg_at_k(["a"], {"a", "b", "c"}, 1) == pytest.approx(1.0)
    assert ndcg_at_k([], {"a"}, 3) == 0.0 and ndcg_at_k(["a"], set(), 3) is None


def test_rrf():
    fused = rrf_fuse([["a", "b", "c"], ["c", "a", "d"]], k=60)
    # a: 1/61 + 1/62; c: 1/63 + 1/61; b: 1/62; d: 1/63
    assert fused == ["a", "c", "b", "d"]
    assert rrf_fuse([["a", "a", "b"]]) == ["a", "b"], "dedupe within a ranking"
    # tie: same score -> smaller best rank first, then id
    assert rrf_fuse([["b", "a"], ["a", "b"]]) == ["a", "b"]
    assert rrf_fuse([]) == []
    # equal scores, different best ranks: x at rank 2 once (1/62) vs y at rank 64 twice (2/124 == 1/62 exactly)
    filler = [f"f{i}" for i in range(62)]
    a = ["f_a", "x"] + []
    b = filler + ["z", "y"]                       # y at rank 64
    c = filler[::-1] + ["w", "y"]                 # y at rank 64
    fused = rrf_fuse([a, b, c])
    assert fused.index("x") < fused.index("y"), "tie broken by the best (smallest) rank: x's 2 beats y's 64"
