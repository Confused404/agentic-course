import json

import pytest

from agentlab.llm import fake
from agentlab.llm.types import ToolResultBlock, ToolUseBlock
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


def _needs(fn, *args):
    try:
        fn(*args)
    except NotImplementedError:
        pytest.skip("needs your AGENT-OFF implementation first (YOU_DO tasks 2-3)")
    except Exception:  # noqa: BLE001 - implemented, just not happy with these args
        pass


@pytest.fixture()
def needs_retry():
    from agentlab.reliability import retry
    _needs(retry.is_retryable, ValueError())


@pytest.fixture()
def needs_recovery():
    from agentlab.reliability import recovery
    _needs(recovery.plan_recovery, [], set())


class Refunder:
    """A STATELESS fake support model: it decides from the transcript alone, so it behaves the same after a resume.
    eligibility -> refund the max refundable -> answer."""
    provider, model = "fake", "refunder"

    def __init__(self, order_id=4822, reason="changed_mind"):
        self.order_id, self.reason, self.calls = order_id, reason, 0

    def complete(self, *, system, messages, tools=None, max_tokens=1024, **opts):
        self.calls += 1
        results = [b for m in messages if m.role == "user" for b in m.content if isinstance(b, ToolResultBlock)]
        uses = {b.id: b.name for m in messages if m.role == "assistant" for b in m.content
                if isinstance(b, ToolUseBlock)}
        if not results:
            r = fake.call("check_refund_eligibility", order_id=self.order_id, reason=self.reason)
        elif uses.get(results[-1].tool_use_id) == "check_refund_eligibility" and not results[-1].is_error:
            amt = json.loads(results[-1].text).get("max_refundable_cents") or 1
            r = fake.call("issue_refund", order_id=self.order_id, amount_cents=amt, reason=self.reason)
        else:
            r = fake.say("Done: " + results[-1].text[:80])
        for i, b in enumerate(r.tool_calls):
            b.id = f"call_{len(results)}_{i}"         # deterministic ids from the transcript, like a real replay
        return r


@pytest.fixture()
def refunder():
    return Refunder
