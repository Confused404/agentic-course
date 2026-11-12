import json
import re
from pathlib import Path

import pytest

from agentlab.llm import fake


@pytest.fixture()
def ws(tmp_path):
    from agentlab.harness import project
    return project.new_workspace(tmp_path / "ws")


@pytest.fixture()
def naive_progress(monkeypatch):
    """Deliberately NAIVE stand-ins for your AGENT-OFF progress functions (YOU_DO task 2), so the harness can be
    tested first. Not solutions: next_feature ignores attempts, validate_update only checks ids, record_attempt
    never counts attempts or truncates notes, stalled never fires."""
    from dataclasses import replace

    from agentlab.harness import progress as P
    monkeypatch.setattr(P, "next_feature", lambda feats, max_attempts=3: next(
        (f for f in feats if f.status != "passing"), None))
    monkeypatch.setattr(P, "validate_update", lambda before, after, allow_passing=False: (
        [] if [f.id for f in before] == [f.id for f in after] else ["ids changed"]))
    # naive: never counts attempts and keeps notes untruncated
    monkeypatch.setattr(P, "record_attempt", lambda feats, fid, passed, notes="": [
        replace(f, status="passing" if passed else "failing", notes=notes) if f.id == fid else f for f in feats])
    monkeypatch.setattr(P, "stalled", lambda counts, window=3: False)


class Worker:
    """A fake coding agent driven by a plan: plan(ws, task, turn, messages) -> list of tool calls (name, args) or a
    final text. Each session (new user message without history) restarts the turn counter."""
    provider, model = "fake", "worker"

    def __init__(self, ws, plan):
        self.ws, self.plan, self.turn, self.sessions, self.seen = Path(ws), plan, 0, 0, []

    def complete(self, *, system, messages, tools=None, max_tokens=1024, **opts):
        if len(messages) == 1:
            self.turn, self.sessions = 0, self.sessions + 1
        self.turn += 1
        self.seen.append({"system": system, "tools": sorted(t.name for t in tools or []),
                          "last": messages[-1].text if messages[-1].role == "user" else ""})
        step = self.plan(self.ws, messages[0].text, self.turn, messages)
        if isinstance(step, str):
            return fake.say(step)
        r = fake.calls(*step)
        for i, b in enumerate(r.tool_calls):
            b.id = f"w{self.sessions}_{self.turn}_{i}"
        return r


def feature_of(task):
    m = re.search(r"feature (F\d)", task)
    return m.group(1) if m else None


def set_status(ws, fid, status, **extra):
    feats = json.loads((ws / "features.json").read_text())
    old = (ws / "features.json").read_text()
    for f in feats:
        if f["id"] == fid:
            f["status"] = status
            f.update(extra)
    return ("edit_file", {"path": "features.json", "old_str": old,
                          "new_str": json.dumps(feats, indent=2) + "\n"})


def liar(ws, task, turn, messages):
    """Claims success without doing anything."""
    fid = feature_of(task)
    if turn == 1 and fid:
        return [set_status(ws, fid, "passing")]
    return "Done! All tests pass."


def box_ticker(ws, task, turn, messages):
    """Writes a passing test file for the feature, and no code: green tests, nothing implemented."""
    fid = feature_of(task)
    if turn == 1 and fid:
        return [("write_file", {"path": f"tests/test_{fid.lower()}.py",
                                "content": "def test_placeholder():\n    assert True\n"})]
    return "Implemented and tested."


@pytest.fixture()
def worker():
    return Worker


@pytest.fixture()
def plans():
    return {"liar": liar, "box_ticker": box_ticker, "set_status": set_status, "feature_of": feature_of}
