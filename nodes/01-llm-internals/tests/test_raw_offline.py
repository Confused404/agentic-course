"""raw.py with injected fake clients: no network, but real control flow (budget, errors, ttft)."""
import json
from types import SimpleNamespace

import pytest

from agentlab.costs import Budget, BudgetExceeded
from agentlab.probe.raw import anthropic_call, openai_compat_call


class Dumpable(SimpleNamespace):
    def __init__(self, d):
        super().__init__(**d)
        self._d = d

    def model_dump(self, **kw):
        return self._d


ANTH = {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": "OK"}], "stop_reason": "end_turn",
        "usage": {"input_tokens": 1000, "output_tokens": 10, "cache_read_input_tokens": 0,
                  "cache_creation_input_tokens": 0}}
OAI = {"id": "c1", "object": "chat.completion", "model": "openai/gpt-5.6-luna",
       "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "OK"}}],
       "usage": {"prompt_tokens": 50, "completion_tokens": 5}}


class FakeAnthropic:
    def __init__(self, fail=None):
        self.sent = None
        self.fail = fail
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.sent = kw
        if self.fail:
            raise self.fail
        return Dumpable(ANTH)


class FakeOpenAI:
    def __init__(self):
        self.sent = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.sent = kw
        return Dumpable(OAI)


def test_anthropic_non_stream_parses_and_charges(tmp_path):
    b = Budget(1.0, "t")
    c = FakeAnthropic()
    r = anthropic_call("claude-haiku-5-5", system="s", messages=[{"role": "user", "content": "hi"}], budget=b,
                       experiment="x", stream=False, client=c, save_raw=tmp_path / "raw.json",
                       output_config={"effort": "low"})
    assert r.text == "OK" and r.input_tokens == 1000 and r.ttft_s is None and r.error is None
    assert r.cost_usd == pytest.approx(1000 * 0.10 / 1e6 + 10 * 0.50 / 1e6)
    assert b.calls == 1 and r.extra["message_id"] == "msg_1"
    assert c.sent["output_config"] == {"effort": "low"} and r.params["output_config"] == {"effort": "low"}
    saved = json.loads((tmp_path / "raw.json").read_text())
    assert saved["response"]["id"] == "msg_1" and "client" not in saved["request"]


def test_errors_become_results_but_budget_propagates():
    r = anthropic_call("claude-haiku-5-5", system="s", messages=[], budget=Budget(1.0), experiment="x",
                       stream=False, client=FakeAnthropic(fail=ValueError("bad request")))
    assert r.error.startswith("ValueError")
    with pytest.raises(BudgetExceeded):
        anthropic_call("claude-haiku-5-5", system="s", messages=[], budget=Budget(0.0000001), experiment="x",
                       stream=False, client=FakeAnthropic())


def test_openai_prepends_system_and_passes_extra():
    c = FakeOpenAI()
    r = openai_compat_call("openrouter", "openai/gpt-5.6-luna", system="be brief",
                           messages=[{"role": "user", "content": "hi"}], budget=Budget(1.0), experiment="x",
                           stream=False, client=c, temperature=0.7)
    assert c.sent["messages"][0] == {"role": "system", "content": "be brief"}
    assert c.sent["temperature"] == 0.7
    assert r.text == "OK" and r.input_tokens == 50 and r.extra["raw_stop_reason"] == "stop"


# ---------------------------------------------------------------- streaming
class FakeAnthropicStream:
    """Mimics `with client.messages.stream(...) as s: for ev in s: ...; s.get_final_message()`."""
    def __init__(self, events, final):
        self.events, self.final = events, final

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self.events)

    def get_final_message(self):
        return Dumpable(self.final)


def test_anthropic_streaming_records_visible_and_any_ttft():
    ev = lambda t, d=None: SimpleNamespace(type=t, delta=SimpleNamespace(type=d) if d else None)  # noqa: E731
    events = [ev("message_start"), ev("content_block_start"), ev("content_block_delta", "thinking_delta"),
              ev("content_block_delta", "text_delta"), ev("message_stop")]
    c = FakeAnthropic()
    c.messages.stream = lambda **kw: FakeAnthropicStream(events, ANTH)
    r = anthropic_call("claude-haiku-5-5", system="s", messages=[], budget=Budget(1.0), experiment="x", client=c)
    assert r.error is None and r.text == "OK"
    assert r.ttft_s is not None and r.extra["ttft_any_s"] is not None
    assert r.extra["ttft_any_s"] <= r.ttft_s, "thinking arrives before visible text"


def _chunk(delta=None, finish=None, usage=None, choices=True):
    c = {"id": "c1", "model": "openai/gpt-5.6-luna", "choices": []}
    if choices:
        c["choices"] = [{"index": 0, "delta": delta or {}, "finish_reason": finish}]
    if usage:
        c["usage"] = usage
    return c


class FakeOpenAIStream(FakeOpenAI):
    def __init__(self, chunks):
        super().__init__()
        self.chunks = chunks

    def _create(self, **kw):
        self.sent = kw
        return iter(self.chunks) if kw.get("stream") else Dumpable(OAI)


def test_openai_streaming_reassembles_tool_arguments_by_index():
    chunks = [
        _chunk({"role": "assistant", "reasoning": "thinking..."}),
        _chunk({"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                "function": {"name": "lookup_order", "arguments": ""}}]}),
        _chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"order_'}}]}),
        _chunk({"tool_calls": [{"index": 1, "id": "call_2", "type": "function",
                                "function": {"name": "lookup_order", "arguments": '{"order_id": 4822}'}}]}),
        _chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'id": 4821}'}}]}),
        _chunk({}, finish="tool_calls"),
        _chunk(usage={"prompt_tokens": 40, "completion_tokens": 9}, choices=False),   # usage-only final chunk
    ]
    c = FakeOpenAIStream(chunks)
    r = openai_compat_call("openrouter", "openai/gpt-5.6-luna", system="s", messages=[], budget=Budget(1.0),
                           experiment="x", client=c)
    assert c.sent["stream"] is True and c.sent["stream_options"] == {"include_usage": True}
    assert [tc["arguments"] for tc in r.tool_calls] == [{"order_id": 4821}, {"order_id": 4822}]
    assert [tc["id"] for tc in r.tool_calls] == ["call_1", "call_2"]
    assert r.input_tokens == 40 and r.output_tokens == 9 and r.stop_reason == "tool_calls"
    assert r.ttft_s is not None and r.extra["ttft_any_s"] <= r.ttft_s
    assert not r.extra.get("usage_missing")


def test_openai_streaming_without_usage_is_flagged():
    chunks = [_chunk({"content": "Hel"}), _chunk({"content": "lo"}), _chunk({}, finish="stop")]
    r = openai_compat_call("ollama", "qwen3:8b", system="s", messages=[], budget=Budget(1.0), experiment="x",
                           client=FakeOpenAIStream(chunks))
    assert r.text == "Hello" and r.extra["usage_missing"] is True and r.input_tokens == 0
