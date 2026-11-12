
import pytest

from agentlab.llm import fake
from agentlab.reliability import faults as F
from agentlab.reliability.resilient import CircuitOpen, ResilientModel


class OK:
    provider, model = "fake", "ok"

    def complete(self, **kw):
        return fake.say("hi")


class Backup(OK):
    provider, model = "fake2", "backup"


def test_retries_then_succeeds(needs_retry):
    slept = []
    m = ResilientModel(F.FaultyModel(OK(), plan=["429:3", "500"]), sleep=slept.append)
    assert m.complete(messages=[]).text == "hi" and m.retries == 2
    assert slept[0] == 3.0, "Retry-After honoured"


class Counting(Backup):
    def __init__(self):
        self.calls = 0

    def complete(self, **kw):
        self.calls += 1
        return super().complete(**kw)


def test_non_retryable_is_raised_at_once(needs_retry):
    inner, backup = F.FaultyModel(OK(), plan=["400"]), Counting()
    with pytest.raises(F.BadRequestError):
        ResilientModel(inner, fallback=backup, sleep=lambda s: None).complete()
    assert inner.calls == 1 and backup.calls == 0, "a bad request is bad on the fallback too"
    with pytest.raises(ValueError):
        ResilientModel(OK(), max_attempts=0)


def test_fallback_is_priced_as_the_fallback(needs_retry):
    m = ResilientModel(F.FaultyModel(OK(), plan=["529"] * 3), max_attempts=3, fallback=Backup(), sleep=lambda s: 0)
    assert m.complete().text == "hi" and (m.provider, m.model) == ("fake2", "backup")
    m.inner.plan = []
    m.complete()
    assert m.model == "ok", "back on the primary once it works"


def test_circuit_breaker(needs_retry):
    t = [0.0]
    m = ResilientModel(F.FaultyModel(OK(), plan=["503"] * 4), max_attempts=2, breaker_threshold=2,
                       breaker_cooldown_s=10, sleep=lambda s: None, clock=lambda: t[0])
    for _ in range(2):
        with pytest.raises(F.ServiceUnavailableError):
            m.complete()
    calls = m.inner.calls
    with pytest.raises(CircuitOpen):
        m.complete()
    assert m.inner.calls == calls, "open circuit: no call to the dead provider"
    t[0] = 11.0
    assert m.complete().text == "hi" and "breaker half-open" in m.events


def test_breaker_with_fallback_skips_the_primary_and_reopens(needs_retry):
    t, backup = [0.0], Counting()
    m = ResilientModel(F.FaultyModel(OK(), plan=["503"] * 6), max_attempts=2, breaker_threshold=1,
                       breaker_cooldown_s=10, fallback=backup, sleep=lambda s: None, clock=lambda: t[0])
    m.complete()                                    # 2 failed attempts -> breaker opens -> fallback answers
    calls = m.inner.calls
    assert m.complete().text == "hi" and m.inner.calls == calls and m.model == "backup", "open: straight to fallback"
    t[0] = 11.0
    m.complete()                                    # half-open probe fails (2 more 503s) -> open again
    assert m.events.count("breaker opened") == 2
    calls = m.inner.calls
    m.complete()
    assert m.inner.calls == calls, "re-opened after the failed probe"


# ----------------------------------------------------------------------------- durable
def _agent(conn, tmp_path, hook=None, **kw):
    from agentlab.assistant.tools import make_support_tools
    from agentlab.reliability.chaos import shop_reconcilers
    from agentlab.reliability.durable import DurableAgent
    from agentlab.reliability.journal import Journal
    j = Journal(tmp_path / "j.db")
    return DurableAgent(j, make_support_tools(conn, 9001, variant="v2"), reconcilers=shop_reconcilers(conn),
                        hook=hook, **kw), j


def _refunds(conn, order=4822):
    return conn.execute("SELECT COUNT(*) FROM refunds WHERE order_id = ?", (order,)).fetchone()[0]


def test_durable_happy_path_and_timeline(conn, tmp_path, refunder, needs_recovery):
    from agentlab.llm.types import Message
    from agentlab.reliability.durable import timeline
    agent, j = _agent(conn, tmp_path)
    r = agent.start("r1", refunder(), "sys", [Message.user("refund 4822")])
    assert r.status == "done" and r.final_text.startswith("Done") and _refunds(conn) == 1
    kinds = [e["kind"] for e in j.entries("r1")]
    assert kinds == ["start", "assistant", "intent", "result", "assistant", "intent", "result", "assistant", "end"]
    assert "issue_refund" in timeline(j.entries("r1"))
    with pytest.raises(ValueError):
        agent.start("r1", refunder(), "sys", [Message.user("again")])


@pytest.mark.parametrize("point,nth", [("journaled", 2), ("journaled", 5), ("executed", 2), ("journaled", 6),
                                       ("journaled", 8)])
def test_crash_anywhere_then_resume_refunds_exactly_once(conn, tmp_path, refunder, needs_recovery, point, nth):
    """Crash after the n-th journal append (or right after the n-th tool ran), then resume in a 'new process'."""
    from agentlab.llm.types import Message
    from agentlab.reliability.faults import Crash
    seen = {"journaled": 0, "executed": 0}

    def hook(p, info):
        seen[p] += 1
        if p == point and seen[p] == nth:
            raise Crash(f"{p} #{nth}")
    agent, j = _agent(conn, tmp_path, hook=hook)
    with pytest.raises(Crash):
        agent.start("r", refunder(), "sys", [Message.user("refund 4822")])
    agent2, _ = _agent(conn, tmp_path)                     # a fresh process: same journal, same DB
    m2 = refunder()
    r = agent2.resume("r", m2)
    assert r.status == "done" and _refunds(conn) == 1, "no double refund, no missing refund"
    assert r.final_text.startswith("Done")
    if (point, nth) == ("journaled", 8):
        assert m2.calls == 0, "the answer was already journaled: finish without asking the model again"
    results = [e for e in j.entries("r") if e["kind"] == "result"]
    assert not any("already exists" in e["content"] and not e.get("reconciled") for e in results)


def test_unknown_side_effect_without_a_reconciler_stops_for_a_human(conn, tmp_path, refunder, needs_recovery):
    from agentlab.llm.types import Message
    from agentlab.reliability.faults import Crash

    def hook(p, info):
        if p == "executed" and info["tool"] == "issue_refund":
            raise Crash("after the refund, before its result")
    agent, j = _agent(conn, tmp_path, hook=hook)
    with pytest.raises(Crash):
        agent.start("r", refunder(), "sys", [Message.user("refund 4822")])
    agent.reconcilers = {}
    agent.hook = lambda p, i: None
    r = agent.resume("r", refunder())
    assert r.status == "needs_human" and _refunds(conn) == 1


def test_human_approval_survives_the_process(conn, tmp_path, refunder, needs_recovery):
    from agentlab.llm.types import Message
    agent, j = _agent(conn, tmp_path, approval_tools={"issue_refund"})
    r = agent.start("r", refunder(), "sys", [Message.user("refund 4822")])
    assert r.status == "awaiting_approval" and _refunds(conn) == 0
    (pend,) = agent.pending_approvals("r")
    with pytest.raises(KeyError):
        agent.approve("r", "nope", True, "maria")
    agent2, _ = _agent(conn, tmp_path, approval_tools={"issue_refund"})     # later, another process
    idle = refunder()
    assert agent2.resume("r", idle).status == "awaiting_approval", "still waiting: nothing decided"
    assert idle.calls == 0, "a resume that's still waiting must not call the model"
    agent2.approve("r", pend["call_id"], True, "maria", "ok")
    with pytest.raises(ValueError):
        agent2.approve("r", pend["call_id"], False, "bob")
    r = agent2.resume("r", refunder())
    assert r.status == "done" and _refunds(conn) == 1


def test_denied_approval_is_a_result_the_model_reads(conn, tmp_path, refunder, needs_recovery):
    from agentlab.llm.types import Message
    agent, j = _agent(conn, tmp_path, approval_tools={"issue_refund"})
    agent.start("r", refunder(), "sys", [Message.user("refund 4822")])
    (pend,) = agent.pending_approvals("r")
    agent.approve("r", pend["call_id"], False, "maria", "fraud check")
    r = agent.resume("r", refunder())
    assert r.status == "done" and _refunds(conn) == 0 and "fraud check" in r.final_text


def test_retry_after_from_sdk_style_errors():
    from agentlab.reliability.resilient import retry_after_s

    class Resp:
        def __init__(self, h):
            self.headers = h

    class SDKError(Exception):
        def __init__(self, h):
            self.response = Resp(h)
    assert retry_after_s(F.RateLimitError(retry_after=2.5)) == 2.5
    assert retry_after_s(SDKError({"retry-after": "7"})) == 7.0
    assert retry_after_s(SDKError({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})) is None
    assert retry_after_s(SDKError({"retry-after": "nan"})) is None
    assert retry_after_s(SDKError({})) is None and retry_after_s(ValueError()) is None


def test_unparseable_arguments_are_never_executed(conn, tmp_path, needs_recovery):
    from agentlab.llm import fake
    from agentlab.llm.types import Message
    agent, j = _agent(conn, tmp_path)
    bad = fake.bad_call("issue_refund", '{"order_id": 4822, "amount_cents": ')
    bad.tool_calls[0].id = "b1"
    r = agent.start("r", fake.ScriptedModel([bad, fake.say("Sorry.")]), "sys", [Message.user("refund 4822")])
    assert r.status == "done" and _refunds(conn) == 0
    res = [e for e in j.entries("r") if e["kind"] == "result"]
    assert res[0]["is_error"] and not [e for e in j.entries("r") if e["kind"] == "intent"]


def test_duplicate_call_ids_are_refused(conn, tmp_path, needs_recovery):
    from agentlab.llm import fake
    from agentlab.llm.types import Message
    agent, _ = _agent(conn, tmp_path)
    twice = fake.ScriptedModel([fake.call("lookup_order", order_id=4822), fake.call("lookup_order", order_id=4821),
                                fake.say("ok")])
    twice.complete = lambda _orig=twice.complete, **kw: _fix(_orig(**kw))
    with pytest.raises(ValueError, match="duplicate"):
        agent.start("r", twice, "sys", [Message.user("hi")])


def _fix(r):
    for b in r.tool_calls:
        b.id = "same"
    return r


def test_budget_stop_keeps_the_paid_answer(conn, tmp_path, refunder, needs_recovery):
    from agentlab.costs import Budget, BudgetExceeded
    from agentlab.llm.types import Message
    agent, j = _agent(conn, tmp_path)
    with pytest.raises(BudgetExceeded):
        agent.start("r", refunder(), "sys", [Message.user("refund 4822")], budget=Budget(limit_usd=1e-12))
    assert [e["kind"] for e in j.entries("r")] == ["start", "assistant"], "journaled before it was charged"


def test_a_human_can_resolve_needs_human(conn, tmp_path, refunder, needs_recovery):
    from agentlab.llm.types import Message
    from agentlab.reliability.faults import Crash

    def hook(p, info):
        if p == "executed" and info["tool"] == "issue_refund":
            raise Crash("after the refund")
    agent, j = _agent(conn, tmp_path, hook=hook)
    with pytest.raises(Crash):
        agent.start("r", refunder(), "sys", [Message.user("refund 4822")])
    agent.reconcilers, agent.hook = {}, (lambda p, i: None)
    r = agent.resume("r", refunder())
    assert r.status == "needs_human"
    with pytest.raises(KeyError):
        agent.resolve_manually("r", "nope", "x", "maria")
    agent.resolve_manually("r", r.note, '{"status": "issued", "note": "checked by hand"}', "maria")
    r = agent.resume("r", refunder())
    assert r.status == "done" and _refunds(conn) == 1


def test_reconcilers_find_what_the_tools_did(conn):
    from shopfront import services
    from agentlab.reliability.chaos import shop_reconcilers
    rec = shop_reconcilers(conn, 9001)
    assert rec["issue_refund"]({"order_id": 4822}) is None
    services.issue_refund(conn, 4822, 100, "changed_mind", actor="agent:t", customer_id=9001)
    assert rec["issue_refund"]({"order_id": 4822})["amount_cents"] == 100
    assert shop_reconcilers(conn, 9002)["issue_refund"]({"order_id": 4822}) is None, "another customer's order"
    summary = "Customer needs help with a damaged order."
    assert rec["escalate_to_human"]({"summary": summary}) is None
    services.escalate_to_human(conn, 9001, summary, None, actor="agent:t")
    assert rec["escalate_to_human"]({"summary": summary})["ticket_id"]
