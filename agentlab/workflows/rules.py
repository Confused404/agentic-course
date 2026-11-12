"""AGENT-OFF: a rule-based triage baseline (Node 09 YOU_DO task 2). No model, no network.

Read TEXTBOOK §1 and §5 first. Tests: nodes/09-workflows/tests/test_rules.py. The point is not to beat the LLM
everywhere: it's to handle the obvious bulk for free, instantly and deterministically, and to ABSTAIN on the rest,
so a model only sees what needs one (the cascade in §5).
"""
from __future__ import annotations

import re
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
    t = " ".join(text.lower().split())
    if not t or any(re.search(p, t) for p in INJECTION):
        return None
    for category, rule, pattern in RULES:
        if re.search(pattern, t):
            prio = "high" if category == "complaint_escalation" else "low" if category == "spam" else "normal"
            return RuleResult(category, prio, rule)
    return None


INJECTION = [r"system override", r"ignore (all )?(previous|prior) instructions", r"you are now", r"as an ai"]
# Order matters: the first rule that fires wins. Narrow, high-precision patterns only; anything vaguer abstains.
RULES: list[tuple[str, str, str]] = [
    ("spam", "spam-marketing", r"\b(seo|click here|you won|free cruise|guest posts?|partnership opportunity)\b"),
    ("complaint_escalation", "legal-or-manager", r"\b(lawyer|chargeback|manager now|third time i'?m writing|"
                                                 r"unacceptable)\b"),
    ("damaged_item", "damaged", r"\b(arrived damaged|came broken|is cracked|big dent|box was crushed)\b"),
    ("cancellation", "cancel-order", r"^(please )?cancel (order )?#?\d+|\bcan i still cancel\b|"
                                     r"\bcancel order #?\d+"),
    ("shipping_status", "where-is", r"\b(where is my order|tracking for \d+|when will order|did #?\d+ ship)\b"),
    ("refund_request", "refund", r"\b(refund (for )?order|money back|return request for|please refund order)\b"),
    ("account", "account", r"\b(can'?t log in|password reset|merge them|change the email on my account)\b"),
    ("product_question", "product-q", r"^(does|is|what'?s|will|can) the [a-z0-9 .()'-]+\?$"),
]
