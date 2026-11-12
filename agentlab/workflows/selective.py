"""AGENT-OFF: selective prediction: when to trust a label and when to hand off (Node 09 YOU_DO task 4).

Read TEXTBOOK §4 first. Tests: nodes/09-workflows/tests/test_selective.py. Only the standard library.
"""
from __future__ import annotations


def coverage_curve(confidences: list[float], correct: list[bool]) -> list[tuple[float, float, float | None]]:
    """For each distinct confidence value t (descending), keep items with confidence >= t and return
    (t, coverage, accuracy): coverage = kept / total, accuracy = correct among kept / kept (None if nothing kept).
    The list starts at the highest threshold (smallest coverage) and ends at the lowest (coverage 1.0).
    Raise ValueError if the lists differ in length; return [] for empty input."""
    raise NotImplementedError("AGENT-OFF")


def pick_threshold(curve: list[tuple[float, float, float | None]], target_accuracy: float) -> float | None:
    """The LOWEST threshold (= the most coverage) whose accuracy is >= target_accuracy, or None if no threshold
    reaches it. why lowest: among thresholds that meet the quality bar, automate as much as possible."""
    raise NotImplementedError("AGENT-OFF")
