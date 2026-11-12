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
def naive_verify(monkeypatch):
    """A deliberately NAIVE verify_token (no signature, expiry or audience checks: it only decodes), so scoped
    sessions can be tested before YOU_DO task 2. Never ship anything like it: that's the point of task 2."""
    from agentlab.authz import tokens as T

    def naive(token, secret, *, audience, required_scopes=frozenset(), now, leeway_s=0):
        payload = json.loads(T.b64url_decode(token.split(".")[1]))
        return T.Principal(payload["sub"], payload.get("cid"), frozenset(payload["scope"].split()), audience,
                           payload["exp"])
    monkeypatch.setattr(T, "verify_token", naive)


class Voter:
    """Thread-safe fake classifier: answers from a function of the prompt text (or a fixed list, cycled)."""
    provider, model = "fake", "voter"

    def __init__(self, answer):
        self.answer, self.n, self.lock, self.prompts = answer, 0, threading.Lock(), []

    def complete(self, *, system, messages, tools=None, max_tokens=1024, **opts):
        with self.lock:
            i = self.n
            self.n += 1
            self.prompts.append((system, messages[0].text, opts))
        a = self.answer(messages[0].text) if callable(self.answer) else self.answer[i % len(self.answer)]
        if a is None:
            return fake.say("I think it's fine")
        return fake.say(json.dumps({"decision": a, "reason": "because"}))


@pytest.fixture()
def voter():
    return Voter
