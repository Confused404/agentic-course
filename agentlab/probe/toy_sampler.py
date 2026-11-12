"""AGENT-OFF: you write this file by hand (nodes/01-llm-internals/YOU_DO.md, task 2).

A toy version of the last step inside a model server: turning logits into one sampled token.
Implement it with numpy only. Read TEXTBOOK §4 first. Tests: nodes/01-llm-internals/tests/test_toy_sampler.py

Contracts:
- softmax(logits, temperature): probabilities summing to 1. temperature must be > 0. Subtract the max
  logit before exponentiating (why? try it without on logits like [1000, 999]).
- top_k_filter(probs, k): zero all but the k largest, renormalize. k >= len(probs) is a no-op.
- top_p_filter(probs, p): keep the SMALLEST set of most-likely tokens whose cumulative probability
  is >= p, zero the rest, renormalize. Always keeps at least one token. p >= 1.0 is a no-op.
- sample(logits, temperature, top_p, top_k, rng): temperature == 0 means greedy (argmax, no rng use).
  Otherwise: softmax with temperature -> top_k (if given) -> top_p -> draw one index with rng.
- empirical_distribution(logits, n, rng, **kw): sample n times, return frequency of each index.
"""
from __future__ import annotations

import numpy as np


def softmax(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    raise NotImplementedError("AGENT-OFF: implement by hand (Node 01 YOU_DO task 2)")


def top_k_filter(probs: np.ndarray, k: int) -> np.ndarray:
    raise NotImplementedError("AGENT-OFF")


def top_p_filter(probs: np.ndarray, p: float) -> np.ndarray:
    raise NotImplementedError("AGENT-OFF")


def sample(logits: np.ndarray, temperature: float = 1.0, top_p: float = 1.0, top_k: int | None = None,
           rng: np.random.Generator | None = None) -> int:
    raise NotImplementedError("AGENT-OFF")


def empirical_distribution(logits: np.ndarray, n: int, rng: np.random.Generator | None = None,
                           **kw) -> np.ndarray:
    raise NotImplementedError("AGENT-OFF")
