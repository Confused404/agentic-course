"""Eval tasks: what to ask, how to grade it, and golden/bad scripts that test the task itself (TEXTBOOK §2, §7)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agentlab.llm import fake

GRADER_TYPES = {"memory_contains", "memory_absent", "refund", "refund_reasons_only", "escalated", "order_status", "no_side_effects", "tools_called",
                "tools_called_any", "tools_not_called", "tool_order", "max_tool_calls", "reply_contains_any",
                "reply_not_contains", "reply_regex", "reply_not_regex", "judge"}


@dataclass
class Task:
    id: str
    customer_id: int
    graders: list[dict]
    turns: list[str] = field(default_factory=list)
    sessions: list[list[str]] | None = None   # Node 06: several conversations in a row, sharing one database
    user_sim: dict | None = None
    tags: list[str] = field(default_factory=list)
    split: str = "dev"
    kind: str = "regression"
    note: str = ""
    golden: list[dict] | None = None
    bad: list[dict] | None = None
    golden_user: list[str] | None = None
    bad_caught_by: list[str] | None = None   # grader types that MUST be among those failing the bad script


def _validate(t: Task) -> None:
    if sum(map(bool, (t.turns, t.user_sim, t.sessions))) != 1:
        raise ValueError(f"task {t.id}: give exactly one of turns / user_sim / sessions")
    if t.sessions and not all(isinstance(s, list) and s for s in t.sessions):
        raise ValueError(f"task {t.id}: every session needs at least one turn")
    if not t.graders:
        raise ValueError(f"task {t.id}: no graders (a task without graders always passes)")
    for g in t.graders:
        if g.get("type") not in GRADER_TYPES:
            raise ValueError(f"task {t.id}: unknown grader type {g.get('type')!r}")


def load_tasks(path: str | Path, split: str | None = None, tags: list[str] | None = None) -> list[Task]:
    path = Path(path)
    files = sorted(path.glob("*.yaml")) if path.is_dir() else [path]
    tasks: list[Task] = []
    for f in files:
        for raw in yaml.safe_load(f.read_text()) or []:
            t = Task(**raw)
            _validate(t)
            tasks.append(t)
    ids = [t.id for t in tasks]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate task ids: {sorted(dupes)}")
    if split:
        tasks = [t for t in tasks if t.split == split]
    if tags:
        tasks = [t for t in tasks if set(tags) & set(t.tags)]
    return tasks


def script_from_steps(steps: list[dict]) -> list:
    out = []
    for s in steps:
        if "say" in s:
            out.append(fake.say(s["say"]))
        elif "call" in s:
            out.append(fake.call(s["call"], **(s.get("args") or {})))
        elif "calls" in s:
            out.append(fake.calls(*[(n, a) for n, a in s["calls"]]))
        else:
            raise ValueError(f"bad step {s}")
    return out
