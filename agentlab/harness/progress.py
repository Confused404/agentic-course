"""The harness's bookkeeping for multi-session work. AGENT-OFF: written by hand in Node 12 YOU_DO task 2.

Feature, STATUSES, load() and save() are GIVEN. Implement next_feature(), validate_update(), record_attempt() and
stalled() to satisfy their docstrings. Tests: nodes/12-harness/tests/test_progress.py. Read TEXTBOOK §3 (state
outside the context window) and §4 (don't trust the agent's own bookkeeping) first. Standard library only.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

STATUSES = ("todo", "in_progress", "passing", "failing")
MAX_NOTES = 500


@dataclass(frozen=True)
class Feature:
    id: str
    title: str
    status: str = "todo"
    attempts: int = 0          # sessions the HARNESS has recorded for this feature
    notes: str = ""            # what the next session should know (e.g. why the last attempt failed)


def load(path: Path) -> list[Feature]:
    return [Feature(**d) for d in json.loads(Path(path).read_text())]


def save(path: Path, features: list[Feature]) -> None:
    Path(path).write_text(json.dumps([asdict(f) for f in features], indent=2) + "\n")


def next_feature(features: list[Feature], max_attempts: int = 3) -> Feature | None:
    """The feature the next session should work on: the FIRST feature in list order whose status is not "passing"
    and whose attempts < max_attempts. (List order is the backlog's order: later features build on earlier ones,
    so we never skip ahead of an unfinished feature that still has attempts left.) None if there is none."""
    raise NotImplementedError("AGENT-OFF: Node 12 YOU_DO task 2")


def validate_update(before: list[Feature], after: list[Feature], *, allow_passing: bool = False) -> list[str]:
    """Problems with an agent's edit of the progress file ([] = acceptable). Contract (each line is tested):

    1. Same feature ids in the same order. Anything else -> exactly one problem mentioning "ids", and stop there.
    2. Per feature (compare before[i] with after[i]); each violation is one problem string that starts with the
       feature id, e.g. "F2: title changed":
       - title must not change ("title");
       - attempts must not change ("attempts"): only the harness counts attempts;
       - status must be one of STATUSES ("status");
       - allowed status changes by the agent: unchanged; todo -> in_progress; failing -> in_progress;
         any -> "passing" only if allow_passing ("passing"); anything else ("status": e.g. passing -> todo,
         anything -> failing, in_progress -> todo);
       - notes must be a str of at most MAX_NOTES characters ("notes").
    3. Problems are listed in feature order, and within a feature in the order of the rules above.
    """
    raise NotImplementedError("AGENT-OFF: Node 12 YOU_DO task 2")


def record_attempt(features: list[Feature], feature_id: str, passed: bool, notes: str = "") -> list[Feature]:
    """The harness's verdict on one session: a NEW list where that feature has attempts + 1, status "passing" or
    "failing", and notes set to `notes` truncated to MAX_NOTES characters. Other features are unchanged; the input
    list is not modified. Unknown feature_id -> KeyError."""
    raise NotImplementedError("AGENT-OFF: Node 12 YOU_DO task 2")


def stalled(passing_counts: list[int], window: int = 3) -> bool:
    """passing_counts[i] = how many features were passing after session i. True when the last `window` sessions
    added nothing: there are more than `window` entries and passing_counts[-1] <= passing_counts[-1 - window].
    (Fewer entries: not enough evidence yet -> False.)"""
    raise NotImplementedError("AGENT-OFF: Node 12 YOU_DO task 2")
