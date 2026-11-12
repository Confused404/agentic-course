"""AGENT-OFF (reference solution). Hand-written in YOU_DO task 2; compare yours with this AFTER writing it.

The last step inside a model server: logits -> one token. See TEXTBOOK §4.
"""
from __future__ import annotations

import numpy as np


def softmax(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    if temperature <= 0:
        raise ValueError("temperature must be > 0 for softmax; use sample(temperature=0) for greedy")
    z = np.asarray(logits, dtype=float) / temperature
    z = z - z.max()                  # why: exp(1000) overflows; shifting by a constant doesn't change softmax
    e = np.exp(z)
    return e / e.sum()


def top_k_filter(probs: np.ndarray, k: int) -> np.ndarray:
    probs = np.asarray(probs, dtype=float)
    if k >= len(probs):
        return probs.copy()
    keep = np.argsort(-probs, kind="stable")[:k]
    out = np.zeros_like(probs)
    out[keep] = probs[keep]
    return out / out.sum()


def top_p_filter(probs: np.ndarray, p: float) -> np.ndarray:
    probs = np.asarray(probs, dtype=float)
    if p >= 1.0:
        return probs.copy()
    order = np.argsort(-probs, kind="stable")
    cum = np.cumsum(probs[order])
    # smallest prefix whose cumulative mass reaches p; always at least one token
    n_keep = int(np.searchsorted(cum, p - 1e-12) + 1)
    n_keep = max(1, min(n_keep, len(probs)))
    out = np.zeros_like(probs)
    out[order[:n_keep]] = probs[order[:n_keep]]
    return out / out.sum()


def sample(logits: np.ndarray, temperature: float = 1.0, top_p: float = 1.0, top_k: int | None = None,
           rng: np.random.Generator | None = None) -> int:
    if temperature == 0:
        return int(np.argmax(logits))    # greedy: deterministic in theory (not in production, TEXTBOOK §4)
    probs = softmax(logits, temperature)
    if top_k is not None:
        probs = top_k_filter(probs, top_k)
    probs = top_p_filter(probs, top_p)
    rng = rng or np.random.default_rng()
    return int(rng.choice(len(probs), p=probs))


def empirical_distribution(logits: np.ndarray, n: int, rng: np.random.Generator | None = None,
                           **kw) -> np.ndarray:
    rng = rng or np.random.default_rng()
    counts = np.zeros(len(logits))
    for _ in range(n):
        counts[sample(logits, rng=rng, **kw)] += 1
    return counts / n
