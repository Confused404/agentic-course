"""GIVEN: the labelled support tickets (Node 09). 240 tickets: 210 from templates, 30 hand-written hard cases
(multi-intent, other languages, no order number, a prompt injection, privacy requests...). Gold labels are in
data/ticket_gold.jsonl, written by `make seed`.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from agentlab.config import ROOT

CATEGORIES = ("refund_request", "damaged_item", "shipping_status", "cancellation", "product_question", "account",
              "complaint_escalation", "spam")
PRIORITIES = ("low", "normal", "high")
GOLD = ROOT / "data" / "ticket_gold.jsonl"


@dataclass(frozen=True)
class Ticket:
    id: int
    customer_id: int | None
    subject: str
    body: str
    channel: str
    category: str                  # gold
    priority: str                  # gold
    secondary: tuple[str, ...] = ()   # other categories a reasonable person might choose
    ambiguous: bool = False
    hard: bool = False
    split: str = "dev"

    def acceptable(self, category: str) -> bool:
        """Is this category an acceptable answer? (the gold one, or a listed secondary)"""
        return category == self.category or category in self.secondary


def split_of(ticket_id: int) -> str:
    # why deterministic and by id: the same ticket is always in the same split, across runs and machines
    return "heldout" if ticket_id % 3 == 0 else "dev"


def load_tickets(conn: sqlite3.Connection, gold_path: Path = GOLD, split: str | None = None,
                 hard: bool | None = None) -> list[Ticket]:
    gold = {g["ticket_id"]: g for g in map(json.loads, Path(gold_path).read_text().splitlines()) if g}
    out = []
    for tid, cid, subject, body, channel in conn.execute(
            "SELECT id, customer_id, subject, body, channel FROM tickets ORDER BY id"):
        g = gold.get(tid)
        if g is None:
            continue              # tickets created during a run (escalations) have no gold label
        t = Ticket(tid, cid, subject, body, channel, g["category"], g["priority"], tuple(g.get("secondary", [])),
                   bool(g.get("ambiguous")), bool(g.get("hard")), split_of(tid))
        if (split is None or t.split == split) and (hard is None or t.hard == hard):
            out.append(t)
    return out
