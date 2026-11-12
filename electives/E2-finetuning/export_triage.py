"""E2: export Node 09's labelled tickets as chat-format JSONL for fine-tuning (train = dev split, eval = held-out).

    .venv/bin/python electives/E2-finetuning/export_triage.py [--out runs/e2]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agentlab.config import RUNS  # noqa: E402
from agentlab.workflows.tickets import CATEGORIES, PRIORITIES, load_tickets  # noqa: E402
from shopfront import db  # noqa: E402

SYSTEM = (f"Classify the Shopfront support ticket. Reply with JSON only: "
          f'{{"category": one of {list(CATEGORIES)}, "priority": one of {list(PRIORITIES)}}}.')


def example(t) -> dict:
    user = f"Channel: {t.channel}\nSubject: {t.subject}\n\n{t.body}"
    answer = json.dumps({"category": t.category, "priority": t.priority})
    return {"id": t.id, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user},
                                     {"role": "assistant", "content": answer}]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(RUNS / "e2"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    conn = db.connect()
    for split, name in (("dev", "train"), ("heldout", "eval")):
        ts = load_tickets(conn, split=split)
        (out / f"{name}.jsonl").write_text("".join(json.dumps(example(t)) + "\n" for t in ts))
        print(f"{name}: {len(ts)} tickets  categories {dict(Counter(t.category for t in ts))}")
    print(f"written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
