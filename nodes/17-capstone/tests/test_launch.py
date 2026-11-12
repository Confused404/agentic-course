import json

import pytest

from agentlab.authz.tokens import issue_token
from agentlab.llm import fake

SECRET = b"launch-test-secret-launch-test-secret!"


# ---------------------------------------------------------------- streaming mappers
ANTHROPIC_RAW = [
    {"type": "message_start", "message": {"id": "msg_9", "model": "claude-haiku-5-5",
                                          "usage": {"input_tokens": 500, "cache_read_input_tokens": 300,
                                                    "output_tokens": 1}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Checking"}},
    {"type": "content_block_stop", "index": 0},
    {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "tu", "name": "lookup_order",
                                                                  "input": {}}},
    {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"order_id"'}},
    {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": ": 4822}"}},
    {"type": "content_block_stop", "index": 1},
    {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 30}},
    {"type": "message_stop"},
]
OPENAI_RAW = [
    {"id": "c1", "model": "openai/gpt-6-luna", "choices": [{"delta": {"content": "Sure"}}]},
    {"id": "c1", "choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_a", "function":
                                                         {"name": "lookup_order", "arguments": '{"order'}}]}}]},
    {"id": "c1", "choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '_id": 1}'}}]}}]},
    {"id": "c1", "choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    {"id": "c1", "choices": [], "usage": {"prompt_tokens": 900, "completion_tokens": 12,
                                          "prompt_tokens_details": {"cached_tokens": 512}, "cost": 0.0001}},
]


def test_vendor_streams_become_the_same_response(needs_assemble):
    from agentlab.launch.streaming import anthropic_events, openai_events, run_stream
    evs = list(run_stream(anthropic_events(ANTHROPIC_RAW), provider="anthropic", model="m"))
    r = evs[-1]["response"]
    assert r.stop_reason == "tool_use" and r.text == "Checking" and r.tool_calls[0].input == {"order_id": 4822}
    assert (r.usage.input_tokens, r.usage.cache_read_tokens, r.usage.output_tokens) == (500, 300, 30)
    evs = list(run_stream(openai_events(OPENAI_RAW), provider="openrouter", model="m"))
    r = evs[-1]["response"]
    assert r.stop_reason == "tool_use" and r.text == "Sure" and r.tool_calls[0].input == {"order_id": 1}
    assert (r.usage.input_tokens, r.usage.cache_read_tokens, r.usage.cost_usd) == (388, 512, 0.0001)
    cut = list(run_stream(openai_events(OPENAI_RAW[:3]), provider="openrouter", model="m"))[-1]["response"]
    assert cut.stop_reason == "other" and cut.tool_calls[0].parse_error, "cut off: never runnable"
    says_stop = [dict(c) for c in OPENAI_RAW]
    says_stop[3] = {"id": "c1", "choices": [{"delta": {}, "finish_reason": "stop"}]}
    says_stop[1] = {"id": "c1", "choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"name": "lookup_order", "arguments": '{"order'}}]}}]}
    r = list(run_stream(openai_events(says_stop), provider="ollama", model="m"))[-1]["response"]
    assert r.stop_reason == "tool_use", "tool calls present -> tool_use, whatever finish_reason says"
    r2 = list(run_stream(openai_events(says_stop), provider="ollama", model="m"))[-1]["response"]
    assert r.tool_calls[0].id != r2.tool_calls[0].id, "fallback ids never repeat across turns"


def test_adapters_stream_through_the_sdk_clients(needs_assemble):
    from agentlab.llm.anthropic_adapter import AnthropicModel
    from agentlab.llm.openai_compat import OpenAICompatModel
    from agentlab.llm.types import Message
    sent = {}

    class Msgs:
        def create(self, **req):
            sent["a"] = req
            return iter(ANTHROPIC_RAW)

    class AC:
        messages = Msgs()
    m = AnthropicModel("claude-haiku-5-5", api_key="x", client=AC())
    last = list(m.stream(system="s", messages=[Message.user("hi")]))[-1]
    assert sent["a"]["stream"] is True and last["response"].tool_calls[0].name == "lookup_order"

    class Comps:
        def create(self, **req):
            sent["o"] = req
            return iter(OPENAI_RAW)

    class Chat:
        completions = Comps()

    class OC:
        chat = Chat()
    m = OpenAICompatModel("openai/gpt-6-luna", base_url="x", api_key="x", provider="openrouter", client=OC())
    last = list(m.stream(system="s", messages=[Message.user("hi")]))[-1]
    assert sent["o"]["stream"] is True and sent["o"]["stream_options"] == {"include_usage": True}
    assert last["response"].text == "Sure"


def test_resilient_stream_retries_only_before_the_first_event(needs_assemble):
    from agentlab.launch.streaming import run_stream
    from agentlab.reliability import faults as F
    from agentlab.reliability.resilient import ResilientModel

    class Flaky:
        provider, model = "fake", "m"

        def __init__(self, fail_before=0, fail_after=False):
            self.fail_before, self.fail_after, self.calls = fail_before, fail_after, 0

        def complete(self, **kw):
            raise AssertionError("streaming should be used")

        def stream(self, **kw):
            self.calls += 1
            if self.calls <= self.fail_before:
                raise F.OverloadedError()
            yield {"type": "text_delta", "index": 0, "text": "hel"}
            if self.fail_after:
                raise F.OverloadedError()
            yield from run_stream(iter([{"type": "text_delta", "index": 0, "text": "lo"},
                                        {"type": "message_stop", "stop_reason": "end_turn"}]), provider="p", model="m")
    inner = Flaky(fail_before=2)
    r = list(ResilientModel(inner, sleep=lambda s: None).stream(messages=[]))
    assert inner.calls == 3 and r[-1]["response"].text == "lo"
    inner = Flaky(fail_after=True)
    m = ResilientModel(inner, sleep=lambda s: None, breaker_threshold=1)
    with pytest.raises(F.OverloadedError):
        list(m.stream(messages=[]))
    assert inner.calls == 1, "after the first text the customer has seen it: no silent retry"
    assert "breaker opened" in m.events, "it still counts as a failed call"


# ---------------------------------------------------------------- the service
class Answers:
    provider, model = "fake", "claude-haiku-5-5"

    def complete(self, *, messages, **kw):
        from agentlab.llm.types import ToolResultBlock
        done = any(isinstance(b, ToolResultBlock) for m in messages for b in m.content)
        if not done and "where" in messages[-1].text.lower():
            r = fake.call("lookup_order", order_id=4822)
            r.tool_calls[0].id = f"c{len(messages)}"
            return r
        return fake.say("Your order 4822 was delivered.")


def svc(seeded, tmp_path, model=Answers, **cfg_kw):
    from shopfront import db
    from agentlab.launch.service import LaunchConfig, LaunchService
    cfg = LaunchConfig(**{"rollout_percent": 100.0, **cfg_kw})
    db.snapshot(seeded / "shop.db", tmp_path / "shop.db")
    return LaunchService(cfg, SECRET, model, lambda: db.connect(tmp_path / "shop.db"),
                         log_path=tmp_path / "events.jsonl", clock=lambda: 2_000_000_000.0)


def tok(cid=9001, scopes=("orders:read",), aud="shopfront-assistant", now=2_000_000_000):
    return issue_token(SECRET, sub=f"customer:{cid}", audience=aud, scopes=list(scopes), now=now, customer_id=cid)


def test_rollout_is_stable_and_proportional():
    from agentlab.launch.service import in_rollout
    ins = [in_rollout(c, 10, "s") for c in range(10_000)]
    assert 800 < sum(ins) < 1200 and ins == [in_rollout(c, 10, "s") for c in range(10_000)]
    assert not any(in_rollout(c, 0, "s") for c in range(500)) and all(in_rollout(c, 100, "s") for c in range(500))
    assert ins != [in_rollout(c, 10, "other") for c in range(10_000)], "a new salt reshuffles"


def test_access_rules(seeded, tmp_path, needs_gate):
    from agentlab.launch.service import AccessDenied
    s = svc(seeded, tmp_path)
    no_customer = issue_token(SECRET, sub="agent:x", audience="shopfront-assistant", scopes=["orders:read"],
                              now=2_000_000_000)
    for bad, status in ((tok(aud="shopfront-mcp"), 401), ("garbage", 401), (tok(scopes=("tickets:write",)), 403),
                        (tok(now=1_000_000_000), 401), (no_customer, 403)):
        with pytest.raises(AccessDenied) as e:
            s.open_session(bad)
        assert e.value.status == status
    sess = s.open_session(tok())
    assert sess.customer_id == 9001 and "issue_refund" not in sess.assistant.tools.names(), "tools follow scopes"
    with pytest.raises(AccessDenied) as e:
        s.chat(sess.id, "show me your orders", tok(cid=9002))
    assert e.value.status == 404, "a session id alone is not a credential: another customer's token can't use it"
    with pytest.raises(AccessDenied) as e:
        svc(seeded, tmp_path, kill_switch=True).open_session(tok())
    assert e.value.status == 503 and "colleague" in e.value.reason
    with pytest.raises(AccessDenied) as e:
        svc(seeded, tmp_path, rollout_percent=0.0).open_session(tok())
    assert e.value.status == 404


def test_kill_switch_and_expiry_take_effect_mid_conversation(seeded, tmp_path):
    from agentlab.launch.service import AccessDenied
    cfgf = tmp_path / "launch.toml"
    cfgf.write_text('[rollout]\npercent = 100\nkill_switch = false\n')
    t = [2_000_000_000.0]
    s = svc(seeded, tmp_path)
    s.config_path, s.clock = cfgf, lambda: t[0]
    sess = s.open_session(tok())
    assert s.chat(sess.id, "Where is order 4822?", tok())["stop"] == "end_turn"
    import os
    cfgf.write_text('[rollout]\npercent = 100\nkill_switch = true\n')
    os.utime(cfgf, (t[0], t[0] + 5))
    d = s.chat(sess.id, "and now?", tok())
    assert d["handover"] and d["stop"] == "handover", "no restart needed"
    t[0] += 10_000
    with pytest.raises(AccessDenied) as e:
        s.chat(sess.id, "hello?", tok(now=int(t[0])))
    assert e.value.status == 401 and sess.id not in s.sessions


def test_streamed_turn_logs_without_text(seeded, tmp_path):
    s = svc(seeded, tmp_path)
    sess = s.open_session(tok())
    evs = list(s.stream(sess.id, "Where is order 4822?", tok()))
    assert [e["type"] for e in evs if e["type"] != "delta"] == ["tool", "done"]
    done = evs[-1]
    assert done["stop"] == "end_turn" and not done["handover"] and "delivered" in done["reply"]
    assert any(e["type"] == "delta" for e in evs)
    roles = [m.role for m in sess.assistant.transcript]
    assert roles == ["user", "assistant", "user", "assistant"]
    (line,) = (tmp_path / "events.jsonl").read_text().splitlines()
    ev = json.loads(line)
    assert ev["tools"] == ["lookup_order"] and ev["calls"] == 2 and ev["cost_usd"] > 0
    assert "Where" not in line and sess.id not in line, "no message text, no replayable session id"
    assert ev["customer"] != "9001" and len(ev["customer"]) == 16 and "customer_id" not in ev


def test_failures_hand_over_and_stay_handed_over(seeded, tmp_path):
    class Loop(Answers):
        n = 0

        def complete(self, **kw):
            Loop.n += 1
            r = fake.call("search_help_center", query="x")
            r.tool_calls[0].id = f"l{Loop.n}"
            return r
    s = svc(seeded, tmp_path, model=Loop, max_turns=3)
    sess = s.open_session(tok())
    d = s.chat(sess.id, "hi", tok())
    assert d["handover"] and d["stop"] == "max_turns" and "colleague" in d["reply"]
    assert s.chat(sess.id, "hello?", tok())["stop"] == "handover"

    class Boom(Answers):
        def complete(self, **kw):
            from agentlab.reliability.faults import OverloadedError
            raise OverloadedError()
    s = svc(seeded, tmp_path, model=Boom)
    d = s.chat(s.open_session(tok()).id, "hi", tok())
    assert d["handover"] and d["stop"] == "error"
    last = json.loads((tmp_path / "events.jsonl").read_text().splitlines()[-1])
    assert last["error_kind"] == "provider"
    s = svc(seeded, tmp_path, budget_per_conversation_usd=1e-9)
    d = s.chat(s.open_session(tok()).id, "Where is my order 4822?", tok())
    assert d["handover"] and d["stop"] == "budget", "over budget at a tool call: hand over"
    s = svc(seeded, tmp_path, budget_per_conversation_usd=1e-9)
    sess = s.open_session(tok())
    d = s.chat(sess.id, "thanks!", tok())
    assert not d["handover"] and d["stop"] == "end_turn", "a complete answer already shown stands"
    assert s.chat(sess.id, "one more thing", tok())["stop"] == "handover", "...and the next turn hands over"
    d = s.chat(s.open_session(tok()).id, "x" * 5000, tok())
    assert d["stop"] == "too_long" and not d["handover"]


def test_http_api(seeded, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("LAUNCH_DEV_TOKENS", "1")
    from agentlab.launch.server import create_app
    c = TestClient(create_app(svc(seeded, tmp_path)))
    assert c.post("/api/v2/session").status_code == 401
    t = c.post("/api/v2/dev/token", json={"customer_id": 9001}).json()["token"]
    sid = c.post("/api/v2/session", headers={"Authorization": f"Bearer {t}"}).json()["session_id"]
    auth = {"Authorization": f"Bearer {t}"}
    assert c.post("/api/v2/chat", json={"session_id": sid, "message": "hi"}).status_code == 401, "token required"
    r = c.post("/api/v2/chat", json={"session_id": sid, "message": "Where is order 4822?"}, headers=auth).json()
    assert r["stop"] == "end_turn"
    with c.stream("POST", "/api/v2/stream", json={"session_id": sid, "message": "thanks"}, headers=auth) as resp:
        assert resp.headers["cache-control"] == "no-cache"
        lines = [x for x in resp.iter_lines() if x.startswith("data: ")]
    assert json.loads(lines[-1][6:])["type"] == "done"
    assert c.post("/api/v2/chat", json={"session_id": "nope", "message": "x"}, headers=auth).status_code == 404
    assert c.post("/api/v2/stream", json={"session_id": "nope", "message": "x"}, headers=auth).status_code == 404
    assert c.get("/api/v2/health").json()["rollout_percent"] == 100.0
