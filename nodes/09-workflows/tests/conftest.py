import json
import threading

import pytest

from agentlab.llm import fake
from shopfront import db
from shopfront.seed import build


@pytest.fixture(scope="session")
def seeded(tmp_path_factory):
    d = tmp_path_factory.mktemp("tmpl")
    build(d / "shop.db", out_dir=d)
    return d


@pytest.fixture()
def conn(seeded, tmp_path):
    c = db.connect(db.snapshot(seeded / "shop.db", tmp_path / "shop.db"))
    yield c
    c.close()


@pytest.fixture()
def tickets(seeded, conn):
    from agentlab.workflows.tickets import load_tickets
    return load_tickets(conn, seeded / "ticket_gold.jsonl")


class JSONModel:
    """Thread-safe fake: each call returns the next label from `labels` (cycled) as triage JSON."""
    provider, model = "fake", "json-fake"

    def __init__(self, labels):
        self.labels, self.n, self.lock, self.calls = list(labels), 0, threading.Lock(), []

    def complete(self, *, system, messages, tools=None, max_tokens=1024, **opts):
        with self.lock:
            lab = self.labels[self.n % len(self.labels)]
            self.n += 1
            self.calls.append({"system": system, "messages": messages, "opts": opts})
        if lab is None:
            return fake.say("not json")
        cat, pri = lab if isinstance(lab, tuple) else (lab, "normal")
        return fake.say(json.dumps({"category": cat, "priority": pri, "needs_human": False}))


@pytest.fixture()
def json_model():
    return JSONModel


@pytest.fixture()
def reference_selective(monkeypatch):
    """A STUB of coverage_curve / pick_threshold (one point, no threshold), so agent-built reports can be tested
    before YOU_DO task 4. Deliberately not a working implementation: that part is yours."""
    from agentlab.workflows import selective as S
    monkeypatch.setattr(S, "coverage_curve",
                        lambda conf, correct: [(min(conf), 1.0, sum(correct) / len(correct))] if conf else [])
    monkeypatch.setattr(S, "pick_threshold", lambda curve, target: None)
