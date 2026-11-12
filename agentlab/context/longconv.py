"""GIVEN: a deterministic generator of long support conversations (Node 06 §1, YOU_DO task 4).

Each task plants something early (a fact, a rule, a nickname for an order), fills the middle with ordinary
questions that make the assistant call tools (help-center searches return long documents, so the context grows
fast), then probes the plant at the very end. A strategy that loses the plant fails the probe. The graders are
state-based (Node 04): what happened in the database, not what the reply sounded like.

    python -m agentlab.context gen --out nodes/06-context-memory/evals/long/long.yaml

Customer 9003 (Priya, standard tier). Orders used (FIXTURES.md): 4831 delivered 30 days ago (last eligible day, any
reason), 4832 delivered 31 days ago (refundable only as `damaged`). She has exactly two delivered orders, so a model
that lost the plant has to ask "which one?" (and the scripted "Yes, go ahead." doesn't answer that) or guess; every
task has a negative grader so a guess of the other order, or of both, fails.

Design note: `constraint_revoked` PASSES under a sliding window for the wrong reason: the rule and its revocation
both fall out of the window, so the model refunds as if neither existed. It discriminates between summaries (which
keep the rule) that do and don't keep the revocation. Read it per strategy, not as a plain score.
"""
from __future__ import annotations

import copy
import random

CUSTOMER = 9003
KINDS = ("refund_recall", "constraint", "constraint_revoked", "alias_action")
LENGTHS = (10, 30, 50)

GREETING = "Hi! I have a few questions today, bear with me."
FILLERS = [
    "How do I season a cast iron pan?",
    "What's your policy on using two promo codes at once?",
    "Do you ship to Canada, and how long does it take?",
    "How long does standard shipping usually take?",
    "My standing desk wobbles at full height. Any setup tips?",
    "What do I get with a Plus membership?",
    "Which payment methods do you accept?",
    "Do gift cards expire?",
    "My LED bulbs flicker on a dimmer. Is that normal?",
    "How should I clean and store a tent after a rainy trip?",
    "How do I change the email address on my account?",
    "What does the warranty cover?",
    "If a price drops after I buy, can I get the difference?",
    "What's your privacy policy on sharing my data?",
    "How do I track an order?",
    "What's the status of order 4831?",
    "What's the status of order 4832?",
    "Can you list my recent orders?",
    "What should I do if a package says delivered but I can't find it?",
    "Is there anything special about returning batteries or power banks?",
    "Can I cancel an order after it ships?",
    "How do I contact a human if I need to?",
    "What's the difference between the 2025 returns policy and the current one?",
    "How do I care for a cast iron pan that has rust spots?",
]

PLANTS = {
    "refund_recall": "Heads up: order 4832 arrived damaged, the item was cracked. I'll deal with it later.",
    "constraint": "One rule for this chat: don't issue any refund unless my message includes the word CONFIRM.",
    "constraint_revoked": "One rule for this chat: don't issue any refund unless my message includes the word CONFIRM.",
    "alias_action": "Order 4831 was a birthday present for my mom, so let's call it 'the birthday order'.",
}
REVOKE = "You can drop the CONFIRM rule I gave you earlier; no need for it anymore."
PROBES = {
    "refund_recall": ["OK, let's deal with that damaged order I mentioned earlier. Please refund it.", "Yes, go ahead."],
    "constraint": ["Please refund order 4831, I changed my mind about it.", "Yes, go ahead."],
    "constraint_revoked": ["Please refund order 4831, I changed my mind about it.", "Yes, go ahead."],
    "alias_action": ["My mom didn't like the birthday order, so I changed my mind about it. Please refund it.",
                     "Yes, go ahead."],
}
GRADERS = {
    "refund_recall": [{"type": "refund", "order_id": 4832, "status": "issued", "reason": "damaged"},
                      {"type": "refund", "order_id": 4831, "status": "none"}],
    "constraint": [{"type": "refund", "order_id": 4831, "status": "none"},
                   {"type": "reply_regex", "pattern": "confirm"}],
    "constraint_revoked": [{"type": "refund", "order_id": 4831, "status": "issued"},
                           {"type": "refund", "order_id": 4832, "status": "none"}],
    "alias_action": [{"type": "refund", "order_id": 4831, "status": "issued"},
                     {"type": "refund", "order_id": 4832, "status": "none"}],
}
NOTES = {
    "refund_recall": "Fact recall: the probe never repeats the order number or the reason. 4832 is refundable only "
                     "as damaged (31 days, standard tier).",
    "constraint": "Instruction persistence: a customer-set rule from turn 2 must still hold at the end.",
    "constraint_revoked": "State tracking: the rule was set, then revoked mid-chat. The latest state must win. "
                          "Passes under a sliding window for the wrong reason (both fall out); discriminates "
                          "summaries that keep the rule but lose the revocation.",
    "alias_action": "Reference resolution: 'the birthday order' (4831) is defined only at turn 2. 9003 has two "
                    "delivered orders; without the alias the model must ask or guess.",
}


def make_long_task(kind: str, n_turns: int, seed: int = 0) -> dict:
    """One task dict in the Node 04 YAML format, exactly `n_turns` customer turns long."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    fixed = 2 + len(PROBES[kind]) + (1 if kind == "constraint_revoked" else 0)   # greeting + plant + probes
    if n_turns < fixed + 1:
        raise ValueError(f"{kind} needs at least {fixed + 1} turns")
    rng = random.Random(f"{kind}:{n_turns}:{seed}")
    pool: list[str] = []
    while len(pool) < n_turns - fixed:
        chunk = FILLERS[:]
        rng.shuffle(chunk)        # why: each filler appears once per cycle; long chats repeat questions, as people do
        pool += chunk
    fillers = pool[: n_turns - fixed]
    middle = fillers
    if kind == "constraint_revoked":
        mid = len(fillers) // 2
        middle = fillers[:mid] + [REVOKE] + fillers[mid:]
    turns = [GREETING, PLANTS[kind], *middle, *PROBES[kind]]
    assert len(turns) == n_turns
    return {"id": f"long_{kind}_{n_turns}", "customer_id": CUSTOMER, "kind": "capability",
            "tags": ["long", kind, f"len{n_turns}"], "turns": turns, "graders": copy.deepcopy(GRADERS[kind]), "note": NOTES[kind]}


def generate_suite(lengths=LENGTHS, kinds=KINDS, seed: int = 0) -> list[dict]:
    return [make_long_task(k, n, seed) for n in lengths for k in kinds]
