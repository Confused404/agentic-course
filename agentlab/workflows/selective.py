"""AGENT-OFF: selective prediction: when to trust a label and when to hand off (Node 09 YOU_DO task 4).

Read TEXTBOOK §4 first. Tests: nodes/09-workflows/tests/test_selective.py. Only the standard library.
"""
from __future__ import annotations


def coverage_curve(confidences: list[float], correct: list[bool]) -> list[tuple[float, float, float | None]]:
    """For each distinct confidence value t (descending), keep items with confidence >= t and return
    (t, coverage, accuracy): coverage = kept / total, accuracy = correct among kept / kept (None if nothing kept).
    The list starts at the highest threshold (smallest coverage) and ends at the lowest (coverage 1.0).
    Raise ValueError if the lists differ in length; return [] for empty input."""
    if len(confidences) != len(correct):
        raise ValueError("confidences and correct differ in length")
    n = len(confidences)
    out = []
    for t in sorted(set(confidences), reverse=True):
        kept = [c for conf, c in zip(confidences, correct) if conf >= t]
        out.append((t, len(kept) / n, (sum(kept) / len(kept)) if kept else None))
    return out


def pick_threshold(curve: list[tuple[float, float, float | None]], target_accuracy: float) -> float | None:
    """The LOWEST threshold (= the most coverage) whose accuracy is >= target_accuracy, or None if no threshold
    reaches it. why lowest: among thresholds that meet the quality bar, automate as much as possible."""
    ok = [t for t, _, acc in curve if acc is not None and acc >= target_accuracy]
    return min(ok) if ok else None
