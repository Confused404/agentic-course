"""AGENT-OFF: retrieval metrics and rank fusion (Node 07 YOU_DO task 3).

Read TEXTBOOK §5-§6 first. Tests: nodes/07-retrieval/tests/test_metrics.py. Only `math` allowed.
All metrics take `ranked`: document ids in rank order (may contain duplicates: count each id once, at its first
position), and `gold`: the set of relevant document ids (binary relevance).
"""
from __future__ import annotations

import math


def dedupe(ranked: list[str]) -> list[str]:
    """GIVEN: first occurrence of each id, order preserved (chunks -> documents)."""
    seen, out = set(), []
    for r in ranked:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def recall_at_k(ranked: list[str], gold: set[str], k: int) -> float | None:
    """|gold ∩ top-k (deduped)| / |gold|. None when gold is empty (undefined: unanswerable questions)."""
    if not gold:
        return None
    return len(set(dedupe(ranked)[:k]) & set(gold)) / len(gold)


def hit_at_k(ranked: list[str], gold: set[str], k: int) -> float | None:
    """1.0 if ANY gold id is in the deduped top-k, else 0.0; None when gold is empty."""
    if not gold:
        return None
    return 1.0 if set(dedupe(ranked)[:k]) & set(gold) else 0.0


def reciprocal_rank(ranked: list[str], gold: set[str]) -> float | None:
    """1 / (1-based rank of the first gold id in the deduped list); 0.0 if none; None when gold is empty."""
    if not gold:
        return None
    for i, r in enumerate(dedupe(ranked), 1):
        if r in gold:
            return 1 / i
    return 0.0


def ndcg_at_k(ranked: list[str], gold: set[str], k: int) -> float | None:
    """Binary-relevance nDCG@k over the deduped list: DCG = Σ_{i=1..k} rel_i / log2(i + 1); IDCG = the DCG of an
    ideal ranking (all gold first, min(|gold|, k) of them). None when gold is empty."""
    if not gold:
        return None
    dcg = sum(1 / math.log2(i + 1) for i, r in enumerate(dedupe(ranked)[:k], 1) if r in gold)
    idcg = sum(1 / math.log2(i + 1) for i in range(1, min(len(gold), k) + 1))
    return dcg / idcg


def rrf_fuse(rankings: list[list[str]], k: int = 60) -> list[str]:
    """Reciprocal Rank Fusion: score(id) = Σ over rankings containing id of 1 / (k + rank), rank 1-based within
    that ranking (deduped first). Return ids by descending score; ties broken by the id's best (smallest) rank
    in any ranking, then by id. why: fuses rankings whose SCORES aren't comparable (BM25 vs cosine)."""
    score: dict[str, float] = {}
    best: dict[str, int] = {}
    for ranking in rankings:
        for rank, r in enumerate(dedupe(ranking), 1):
            score[r] = score.get(r, 0.0) + 1 / (k + rank)
            best[r] = min(best.get(r, rank), rank)
    return sorted(score, key=lambda r: (-score[r], best[r], r))
