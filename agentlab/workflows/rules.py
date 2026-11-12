"""AGENT-OFF: a rule-based triage baseline (Node 09 YOU_DO task 2). No model, no network.

Read TEXTBOOK §1 and §5 first. Tests: nodes/09-workflows/tests/test_rules.py. The point is not to beat the LLM
everywhere: it's to handle the obvious bulk for free, instantly and deterministically, and to ABSTAIN on the rest,
so a model only sees what needs one (the cascade in §5).
"""
from __future__ import annotations

from dataclasses import dataclass

from agentlab.workflows.tickets import CATEGORIES, PRIORITIES  # noqa: F401


@dataclass(frozen=True)
class RuleResult:
    category: str          # one of CATEGORIES
    priority: str          # one of PRIORITIES
    rule: str              # a short name for the rule that fired (for debugging and the stage report)


def classify_by_rules(text: str) -> RuleResult | None:
    """Return a label when a rule is confident, else None (abstain).

    Contract (the tests check each item):
    1. Pure and deterministic; never raises on any str; returns None or a RuleResult with a valid category and
       priority.
    2. Precision first: on the dev split's NON-hard tickets, the rules must label at least 70% (coverage) with at
       least 95% of those correct. Wrong answers cost more than abstentions: a wrong label routes a ticket to the
       wrong queue, an abstention just sends it to the next stage.
    3. On the hard tickets, abstain on at least half: rules shouldn't pretend to understand "I want a refund. Also
       I'm never shopping here again".
    4. Priority: "high" for complaint_escalation, "low" for spam, "normal" otherwise.
    5. Never label text that contains instructions aimed at a system ("SYSTEM OVERRIDE", "ignore previous
       instructions"): abstain, and let a later stage (or a human) decide.
    """
    raise NotImplementedError("AGENT-OFF: write classify_by_rules (Node 09 YOU_DO task 2)")
