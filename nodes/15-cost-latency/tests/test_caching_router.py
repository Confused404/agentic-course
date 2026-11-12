import datetime as dt

import pytest

from agentlab.costs import Budget
from agentlab.llm import fake
from agentlab.llm.types import Message, TextBlock, ToolResultBlock, ToolUseBlock, Usage
from agentlab.perf.recorder import RecordingModel


class Capture:
    """Records what it was sent; answers from a script of responses (or "hi")."""
    def __init__(self, provider="fake", model="m", script=None):
        self.provider, self.model, self.sent, self.script = provider, model, [], list(script or [])

    def complete(self, **kw):
        self.sent.append(kw)
        return self.script.pop(0) if self.script else fake.say("hi")


# ---------------------------------------------------------------- caching
def test_cache_policies_lay_out_requests():
    from agentlab.perf.caching import CachePolicyModel
    inner = Capture()
    CachePolicyModel(inner, "off").complete(system="S", messages=[], cache=True)
    assert "cache" not in inner.sent[-1] and inner.sent[-1]["system"] == "S"
    CachePolicyModel(inner, "auto").complete(system="S", messages=[])
    assert inner.sent[-1]["cache"] is True and inner.sent[-1]["system"] == "S"
    CachePolicyModel(inner, "explicit").complete(system="S", messages=[])
    s = inner.sent[-1]["system"]
    assert inner.sent[-1]["cache"] is True and isinstance(s, list) and s[0].text == "S" and s[0].cache
    t = dt.datetime(2026, 11, 4, 9, 30, 5, tzinfo=dt.timezone.utc)
    m = CachePolicyModel(inner, "timestamp", now=lambda: t)
    m.complete(system=[TextBlock("S")], messages=[])
    assert inner.sent[-1]["system"].startswith("Current time: 2026-11-04T09:30:05") and \
        inner.sent[-1]["system"].endswith("S")
    assert m.model == "m" and m.provider == "fake"
    with pytest.raises(ValueError):
        CachePolicyModel(inner, "sometimes")


def _rec(model, system, messages, read=0, total=1000, opts=None, t=0.0):
    return {"seq": 0, "model": model, "provider": "anthropic", "t_start": t,
            "request": {"tools": [], "system": system, "messages": messages,
                        "opts": {"cache": True} if opts is None else opts},
            "usage": {"input_tokens": total - read, "output_tokens": 5, "cache_read_tokens": read,
                      "cache_write_tokens": 0}}


def test_doctor_compares_calls_to_the_same_model(needs_prefix):
    from agentlab.perf.caching import cache_summary, diagnose
    sys_ = "x" * 4000
    u1 = {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    a1 = {"role": "assistant", "content": [{"type": "text", "text": "yo"}]}
    recs = [_rec("cheap", sys_, [u1]), _rec("strong", sys_, [u1]), _rec("cheap", sys_, [u1, a1, u1], read=900),
            _rec("cheap", "Current time: 1\n" + sys_, [u1, a1, u1, a1, u1])]
    rows = diagnose(recs)
    assert [r["section"] for r in rows] == ["first", "first", "extends", "system"]
    assert rows[2]["read_share"] == pytest.approx(0.9) and "below" not in rows[2]["why"]
    s = cache_summary([recs])
    assert s["calls"] == 4 and s["cache_read_tokens"] == 900 and s["divergences"]["system"] == 1
    assert "wrote the cache" not in rows[0]["why"], "nothing was written (cache_write_tokens == 0)"


def test_doctor_explains_misses_the_prefix_cant(needs_prefix):
    from agentlab.perf.caching import diagnose
    sys_ = "x" * 4000
    u1 = {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    rows = diagnose([_rec("m", sys_, [u1], opts={}), _rec("m", sys_, [u1, u1], opts={})])
    assert "nothing was read" in rows[1]["why"] and "wasn't requested" in rows[1]["why"]
    rows = diagnose([_rec("m", sys_, [u1], t=0), _rec("m", sys_, [u1, u1], opts={"cache": True, "effort": "low"},
                                                      t=900)])
    assert "options changed" in rows[1]["why"] and "expired" in rows[1]["why"]


# ---------------------------------------------------------------- router
def test_cascade_keeps_cheap_answers_and_escalates_risky_steps():
    from agentlab.perf.router import CascadeModel
    cheap = Capture("p1", "claude-haiku-5-5", [fake.say("Your order shipped."),
                                               fake.call("issue_refund", order_id=1, amount_cents=5)])
    strong = Capture("p2", "claude-sonnet-5-5", [fake.call("issue_refund", order_id=1, amount_cents=5),
                                                 fake.say("done")])
    b = Budget(limit_usd=1.0)
    c = CascadeModel(cheap, strong, budget=b)
    r = c.complete(system="s", messages=[Message.user("where?")])
    assert r.text == "Your order shipped." and c.model == "claude-haiku-5-5" and c.escalations == 0
    r = c.complete(system="s", messages=[Message.user("refund it")])
    assert r.tool_calls[0].name == "issue_refund" and c.model == "claude-sonnet-5-5"
    assert c.escalations == 1 and c.reasons[0].startswith("high-stakes") and c.wasted_usd > 0
    assert b.calls == 1, "the discarded cheap answer is charged (the loop charges the one it receives)"
    c.complete(system="s", messages=[Message.user("thanks")])
    assert len(cheap.sent) == 2 and len(strong.sent) == 2, "sticky: stays on the strong model"


def test_cascade_other_reasons():
    from agentlab.perf.router import CascadeModel
    err = [Message.user("x"), Message("assistant", [ToolUseBlock("t1", "lookup_order", {})]),
           Message("user", [ToolResultBlock("t1", "boom", is_error=True)])]
    cheap = Capture(script=[fake.say("ok")])
    c = CascadeModel(cheap, Capture(model="s"), sticky=False)
    c.complete(system="s", messages=err)
    assert c.reasons == ["recent tool error"] and cheap.sent == [], "input-only signal: no cheap call to throw away"
    c.complete(system="s", messages=err + [Message("assistant", [fake.say("hm").content[0]]), Message.user("new q")])
    assert len(cheap.sent) == 1, "an error from an earlier customer turn doesn't escalate the next one"
    c = CascadeModel(Capture(script=[fake.bad_call("lookup_order", "{")]), Capture(model="s"), sticky=False)
    c.complete(system="s", messages=[Message.user("x")])
    assert c.reasons == ["unparseable tool arguments"]
    c = CascadeModel(Capture(script=[fake.say("")]), Capture(model="s"), sticky=False)
    c.complete(system="s", messages=[Message.user("x")])
    c.complete(system="s", messages=[Message.user("y")])
    assert c.reasons == ["empty answer"] and c.escalations == 1, "not sticky: the next call starts cheap again"


def test_recorder_records_failures_too():
    class Boom(Capture):
        def complete(self, **kw):
            raise RuntimeError("down")
    sink = []
    m = RecordingModel(Boom(), sink, label="fast")
    with pytest.raises(RuntimeError):
        m.complete(system="s", messages=[Message.user("x")])
    assert sink[0]["error"].startswith("RuntimeError") and sink[0]["label"] == "fast" and sink[0]["usage"] is None
    RecordingModel(Capture(), sink).complete(system="s", messages=[], max_tokens=10, effort="low")
    assert sink[1]["request"]["opts"] == {"effort": "low"} and sink[1]["usage"]["output_tokens"] >= 1
    assert Usage(**{k: v for k, v in sink[1]["usage"].items()}).output_tokens >= 1
