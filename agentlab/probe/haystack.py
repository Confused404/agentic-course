"""Deterministic long documents with a 'needle' at a chosen position.

Filler = help-center paragraphs (each used once) followed by generated "ops memos". Why memos: the help
center is only ~3K tokens; cycling it to 30K would make the document 90% exact repeats, and recall in
low-entropy repeated text is unrealistically easy. Memos are unique and full of dates, places and
4-digit numbers that look like the needle, which is what makes real long contexts hard (TEXTBOOK §7).
"""
from __future__ import annotations

import random
from pathlib import Path

from agentlab.config import ROOT

CORPUS = ROOT / "data" / "help_center"
CITIES = ["Halifax", "Montreal", "Toronto", "Denver", "Austin", "Portland"]
SUPPLIERS = ["Northwind", "Bluepeak", "Granite & Co", "Saltmarsh Supply", "Kestrel Outdoor"]
CATEGORIES = ["kitchen", "outdoor", "lighting", "bags", "home-office", "electronics accessories"]
PEOPLE = ["A. Moreau", "K. Sato", "R. Haddad", "L. Osei", "M. Novak", "S. Berg"]


def estimate_tokens(text: str) -> int:
    # why: a free, instant estimate for sizing; vendor counts differ (TEXTBOOK §2, experiment E1)
    return len(text) // 4


def ops_memo(rng: random.Random) -> str:
    d = f"2026-{rng.randint(1, 10):02d}-{rng.randint(1, 28):02d}"
    d2 = f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
    c, s, cat, who = rng.choice(CITIES), rng.choice(SUPPLIERS), rng.choice(CATEGORIES), rng.choice(PEOPLE)
    n4 = rng.randint(1000, 9999)
    templates = [
        f"Ops memo {d}: the {c} warehouse received {rng.randint(40, 900)} units of SKU {cat[:3].upper()}-{rng.randint(1, 60):04d} "
        f"from {s}; {rng.randint(0, 12)} arrived damaged and were logged under claim #{n4}.",
        f"Shift note {d}: forklift F-{rng.randint(1, 9)} at {c} is out of service until {d2}; use bay {rng.randint(1, 24)} "
        f"for returns. Locker {n4} holds the spare keys.",
        f"Vendor update {d}: {s} raises prices on {cat} by {rng.randint(2, 15)}% effective {d2}; purchase order "
        f"{n4} is grandfathered at the old rate.",
        f"Returns insight {d}: {rng.randint(5, 60)}% of {cat} returns from {c} cite '{rng.choice(['wrong size', 'arrived late', 'not as pictured', 'changed mind'])}'.",
        f"IT notice {d}: the {rng.choice(['badge', 'scanner', 'VPN', 'printer'])} system at {c} rotates credentials on {d2}; "
        f"contact {who} at extension {n4}.",
        f"Safety log {d}: {c} ran a fire drill at {rng.randint(7, 17)}:{rng.choice(['00', '15', '30', '45'])}; "
        f"evacuation took {rng.randint(3, 11)} minutes. Next drill {d2}.",
    ]
    return rng.choice(templates)


def _paragraphs(corpus_dir: Path) -> list[str]:
    paras: list[str] = []
    for f in sorted(corpus_dir.glob("*.md")):      # sorted: filesystem order is not deterministic
        text = f.read_text()
        if text.startswith("---"):
            parts = text.split("---", 2)
            text = parts[2] if len(parts) == 3 else text
        paras += [p.strip() for p in text.split("\n\n") if p.strip()]
    return paras


def build_haystack(target_tokens: int, needle: str, position: float, distractors: list[str] = (),
                   seed: int = 0, corpus_dir: Path = CORPUS) -> str:
    rng = random.Random(seed)
    pool = _paragraphs(corpus_dir)
    rng.shuffle(pool)
    out: list[str] = []
    seen: set[str] = set()
    i = 0
    while estimate_tokens("\n\n".join(out)) < target_tokens:
        p = pool[i] if i < len(pool) else ops_memo(rng)
        i += 1
        if p not in seen:          # never repeat a paragraph
            seen.add(p)
            out.append(p)
    # distractors first, at seeded positions; then the needle at its exact relative position
    for d in distractors:
        out.insert(rng.randint(0, len(out)), d)
    out.insert(round(position * len(out)), needle)
    return "\n\n".join(out)


def needle_position(text: str, needle: str) -> float:
    i = text.find(needle)
    return -1.0 if i < 0 else i / max(len(text), 1)
