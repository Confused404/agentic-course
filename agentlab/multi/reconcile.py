"""Merging worker reports. AGENT-OFF (reference solution): written by hand in Node 10 YOU_DO task 2.

The dataclasses are GIVEN (the architectures import them). Implement reconcile() to satisfy its docstring.
Tests: nodes/10-multi-agent/tests/test_reconcile.py. Read TEXTBOOK §5 (the merge is where multi-agent systems
silently lose work) first.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WorkerReport:
    shard: str                      # the shard this worker was assigned (e.g. a category)
    items: dict                     # key -> value, as the worker reported them (e.g. SKU -> stats)
    notes: str = ""                 # anything the worker wants the lead to know (caveats, partial work)
    ok: bool = True                 # False: the worker failed to report (crash, budget, never called report)
    error_kind: str | None = None   # for ok=False from an exception: "provider" (rate limit, outage) or "agent"


@dataclass
class Reconciled:
    merged: dict                                            # key -> value, sorted by key
    missing_shards: list[str] = field(default_factory=list)      # expected, but no ok report
    duplicates: list[str] = field(default_factory=list)          # keys reported by 2+ shards with EQUAL values
    conflicts: dict[str, list] = field(default_factory=dict)     # key -> the distinct values, in report order
    unexpected_shards: list[str] = field(default_factory=list)   # reported, but not expected
    notes: dict[str, str] = field(default_factory=dict)          # shard -> notes, for ok reports with notes


def reconcile(expected_shards: list[str], reports: list[WorkerReport]) -> Reconciled:
    """Merge worker reports without silently losing or inventing anything. Contract (each line is tested):

    1. Reports are processed in list order. If the same shard reports more than once, its LAST report replaces
       the earlier ones entirely (a retry supersedes a failed or partial attempt), including an ok=False report
       replacing an ok one.
    2. A shard in expected_shards with no report, or whose (last) report has ok=False, is missing.
       missing_shards keeps the order of expected_shards.
    3. A report whose shard is not in expected_shards is unexpected: listed in unexpected_shards (sorted, no
       repeats) and its items are NOT merged (a worker that wandered off its assignment is not evidence).
    4. Items from the remaining (ok, expected) reports are merged. A key reported by several shards:
         - all values equal (==): keep it once and list the key in duplicates;
         - any two values differ: put it in conflicts with its distinct values, in the order of the shards'
           FIRST report in the list (a retried shard keeps its original position), and leave it OUT of merged
           (don't pick a winner silently: the caller decides).
       Superseded and ok=False reports contribute nothing: no items, no notes.
       A key is in duplicates or conflicts, never both. duplicates and conflicts keys are sorted.
    5. merged is a new dict with keys in sorted order (compare keys as strings). Never mutate the reports.
    6. notes maps shard -> notes.strip() for merged reports whose stripped notes are non-empty.
    """
    latest: dict[str, WorkerReport] = {}
    for r in reports:
        latest[r.shard] = r            # why: a retry supersedes everything that shard said before (contract 1)
    expected = set(expected_shards)
    missing = [s for s in expected_shards if s not in latest or not latest[s].ok]
    unexpected = sorted({s for s in latest if s not in expected})

    seen: dict[str, list] = {}         # key -> distinct values, in first-seen order
    counts: dict[str, int] = {}
    notes: dict[str, str] = {}
    for shard, r in latest.items():    # dicts keep insertion order: the order shards first reported
        if shard not in expected or not r.ok:
            continue
        if r.notes and r.notes.strip():
            notes[shard] = r.notes.strip()
        for k, v in r.items.items():
            counts[k] = counts.get(k, 0) + 1
            vals = seen.setdefault(k, [])
            if not any(v == x for x in vals):
                vals.append(v)
    conflicts = {k: list(seen[k]) for k in sorted(seen, key=str) if len(seen[k]) > 1}
    duplicates = sorted((k for k in seen if counts[k] > 1 and len(seen[k]) == 1), key=str)
    # why: a conflicting key is withheld rather than resolved by order: "last writer wins" is a silent guess
    merged = {k: seen[k][0] for k in sorted(seen, key=str) if len(seen[k]) == 1}
    return Reconciled(merged, missing, duplicates, conflicts, unexpected, notes)
