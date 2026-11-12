"""Pure adapter functions: canonical types <-> vendor wire formats (TEXTBOOK §4)."""
import json
from types import SimpleNamespace

from agentlab.llm.anthropic_adapter import AnthropicModel, from_anthropic_response, to_anthropic_request
from agentlab.llm.openai_compat import OpenAICompatModel, from_openai_response, to_openai_request
from agentlab.llm.types import (ImageBlock, Message, TextBlock, ThinkingBlock, ToolResultBlock, ToolSpec,
                                ToolUseBlock)

TOOLS = [ToolSpec("lookup_order", "Look up an order", {"type": "object", "properties": {"order_id": {"type": "integer"}}})]
CONVO = [
    Message.user("Where is 4821?"),
    Message("assistant", [ThinkingBlock("check it", provider="anthropic", provider_data={"signature": "SIG"}),
                          ThinkingBlock("other vendor", provider="openrouter", provider_data={"reasoning_details": [1]}),
                          TextBlock("Looking."), ToolUseBlock("tu1", "lookup_order", {"order_id": 4821})]),
    Message("user", [ToolResultBlock("tu1", '{"status": "delivered"}'), TextBlock("also, thanks")]),
]


# ------------------------------------------------------------- Anthropic
def test_anthropic_request_mapping():
    req, dropped = to_anthropic_request(model="m", system="be nice", messages=CONVO, tools=TOOLS, max_tokens=500,
                                        opts={"effort": "low", "temperature": 0.2, "tool_choice": "any",
                                              "json_schema": {"type": "object"}})
    assert req["system"] == "be nice" and req["max_tokens"] == 500 and req["model"] == "m"
    assert req["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": {"type": "object"}}}
    assert req["tool_choice"] == {"type": "any"} and "temperature" not in req and dropped == ["temperature"]
    assert req["tools"] == [{"name": "lookup_order", "description": "Look up an order",
                             "input_schema": TOOLS[0].input_schema}]
    a = req["messages"][1]["content"]
    assert a[0] == {"type": "thinking", "thinking": "check it", "signature": "SIG"}
    assert [b["type"] for b in a] == ["thinking", "text", "tool_use"], "foreign thinking is dropped"
    u = req["messages"][2]["content"]
    assert u[0] == {"type": "tool_result", "tool_use_id": "tu1", "content": '{"status": "delivered"}', "is_error": False}


def test_anthropic_system_blocks_cache_and_images():
    msgs = [Message("user", [TextBlock("doc", cache=True), ImageBlock("image/png", "AAAA")]),
            Message("assistant", [ToolUseBlock("t", "x", {})]),
            Message("user", [ToolResultBlock("t", [TextBlock("shot"), ImageBlock("image/png", "BBBB")], is_error=True)])]
    req, _ = to_anthropic_request(model="m", system=[TextBlock("A"), TextBlock("B", cache=True)], messages=msgs,
                                  tools=None, max_tokens=10, opts={"cache": True, "tool_choice": {"name": "x"}})
    assert req["system"][1]["cache_control"] == {"type": "ephemeral"} and "cache_control" not in req["system"][0]
    assert req["cache_control"] == {"type": "ephemeral"} and req["tool_choice"] == {"type": "tool", "name": "x"}
    assert "tools" not in req
    assert req["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert req["messages"][0]["content"][1]["source"] == {"type": "base64", "media_type": "image/png", "data": "AAAA"}
    tr = req["messages"][2]["content"][0]
    assert tr["is_error"] and tr["content"][1]["type"] == "image"


def test_anthropic_response_mapping():
    data = {"id": "msg_1", "model": "claude-haiku-5-5", "stop_reason": "model_context_window_exceeded",
            "content": [{"type": "thinking", "thinking": "hmm", "signature": "S1"},
                        {"type": "redacted_thinking", "data": "XYZ"},
                        {"type": "text", "text": "Hi"},
                        {"type": "tool_use", "id": "toolu_9", "name": "lookup_order", "input": {"order_id": 1}}],
            "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 3,
                      "cache_creation_input_tokens": None, "output_tokens_details": {"thinking_tokens": 2}}}
    r = from_anthropic_response(data, latency_s=1.5)
    assert r.stop_reason == "context_window_exceeded" and r.raw_stop_reason == "model_context_window_exceeded"
    assert r.id == "msg_1" and r.provider == "anthropic" and r.latency_s == 1.5 and r.text == "Hi"
    t0, t1 = r.content[0], r.content[1]
    assert t0.provider == "anthropic" and t0.provider_data == {"signature": "S1"}
    assert t1.provider_data == {"redacted_data": "XYZ"}
    assert r.tool_calls[0].input == {"order_id": 1} and r.tool_calls[0].provider == "anthropic"
    u = r.usage
    assert (u.input_tokens, u.output_tokens, u.cache_read_tokens, u.cache_write_tokens, u.reasoning_tokens) == (10, 5, 3, 0, 2)
    # round trip: redacted thinking goes back as redacted_thinking
    req, _ = to_anthropic_request(model="m", system="", messages=[Message("assistant", r.content)], tools=None,
                                  max_tokens=1, opts={})
    assert req["messages"][0]["content"][1] == {"type": "redacted_thinking", "data": "XYZ"} and "system" not in req


def test_anthropic_model_uses_injected_client():
    sent = {}

    class Resp:
        def model_dump(self):
            return {"id": "m1", "model": "x", "stop_reason": "end_turn", "content": [{"type": "text", "text": "ok"}],
                    "usage": {"input_tokens": 1, "output_tokens": 1}}
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: (sent.update(kw), Resp())[1]))
    m = AnthropicModel("claude-haiku-5-5", client=client)
    r = m.complete(system="s", messages=[Message.user("hi")], max_tokens=50, temperature=0.5)
    assert r.text == "ok" and sent["max_tokens"] == 50 and m.last_dropped_opts == ["temperature"]


# ------------------------------------------------------------- OpenAI-compatible
def test_openai_request_mapping():
    req, dropped = to_openai_request(model="m", system=[TextBlock("A"), TextBlock("B", cache=True)], messages=CONVO,
                                     tools=TOOLS, max_tokens=300, provider="openrouter",
                                     opts={"effort": "low", "temperature": 0.2, "tool_choice": "any", "cache": True})
    msgs = req["messages"]
    assert msgs[0] == {"role": "system", "content": "A\n\nB"}
    assert msgs[1] == {"role": "user", "content": "Where is 4821?"}
    a = msgs[2]
    assert a["role"] == "assistant" and a["content"] == "Looking."
    assert a["tool_calls"] == [{"id": "tu1", "type": "function",
                                "function": {"name": "lookup_order", "arguments": json.dumps({"order_id": 4821})}}]
    assert a["reasoning_details"] == [1], "same-provider reasoning round-trips; anthropic thinking dropped"
    assert msgs[3] == {"role": "tool", "tool_call_id": "tu1", "content": '{"status": "delivered"}'}
    assert msgs[4] == {"role": "user", "content": "also, thanks"}
    assert req["extra_body"]["reasoning"] == {"effort": "low"}, "OpenRouter's unified reasoning control"
    assert req["temperature"] == 0.2 and req["tool_choice"] == "required"
    assert req["tools"][0] == {"type": "function", "function": {"name": "lookup_order", "description": "Look up an order",
                                                                "parameters": TOOLS[0].input_schema}}
    assert req["extra_body"]["usage"] == {"include": True} and req["max_tokens"] == 300
    assert dropped == ["cache"]


def test_openrouter_fallback_models():
    req, dropped = to_openai_request(model="a:free", system="", messages=[Message.user("hi")], tools=None,
                                     max_tokens=10, provider="openrouter", opts={"fallback_models": ["b:free"]})
    assert req["extra_body"]["models"] == ["a:free", "b:free"] and not dropped, "the primary goes first"
    req, dropped = to_openai_request(model="m", system="", messages=[Message.user("hi")], tools=None,
                                     max_tokens=10, provider="ollama", opts={"fallback_models": ["x"]})
    assert "models" not in req.get("extra_body", {}) and dropped == ["fallback_models"]


def test_openai_errors_images_and_bad_args_roundtrip():
    msgs = [Message("assistant", [ToolUseBlock("c1", "x", {}, raw_arguments='{"a": ', parse_error="bad")]),
            Message("user", [ToolResultBlock("c1", [TextBlock("see image"), ImageBlock("image/png", "QQ")], is_error=True)])]
    req, _ = to_openai_request(model="m", system="", messages=msgs, tools=None, max_tokens=5, opts={}, provider="ollama")
    m = req["messages"]
    assert m[0]["tool_calls"][0]["function"]["arguments"] == '{"a": ', "send back exactly what the model wrote"
    assert m[1] == {"role": "tool", "tool_call_id": "c1", "content": "ERROR: see image"}
    assert m[2]["role"] == "user" and m[2]["content"][0] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,QQ"}}
    assert "extra_body" not in req and "tools" not in req


def test_openai_response_mapping():
    data = {"id": "c9", "model": "", "choices": [{"finish_reason": "stop", "message": {
        "content": "", "reasoning": "thinking...", "reasoning_details": [{"type": "x"}],
        "tool_calls": [{"type": "function", "function": {"name": "lookup_order", "arguments": '{"order_id": 4821}'}},
                       {"id": "k", "type": "function", "function": {"name": "lookup_order", "arguments": "[1]"}}]}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 40},
                  "completion_tokens_details": {"reasoning_tokens": 7}, "cost": 0.001}}
    r = from_openai_response(data, provider="openrouter")
    assert r.stop_reason == "tool_use" and r.raw_stop_reason == "stop" and r.provider == "openrouter"
    assert isinstance(r.content[0], ThinkingBlock) and r.content[0].provider_data == {"reasoning_details": [{"type": "x"}]}
    a, b = r.tool_calls
    assert a.id.startswith("call_") and a.input == {"order_id": 4821} and a.parse_error is None
    assert b.input == {} and b.parse_error and b.raw_arguments == "[1]"
    u = r.usage
    assert (u.input_tokens, u.cache_read_tokens, u.output_tokens, u.reasoning_tokens, u.cost_usd) == (60, 40, 20, 7, 0.001)
    assert r.text == ""


def test_openai_stop_mapping():
    def fr(f):
        return from_openai_response({"choices": [{"finish_reason": f, "message": {"content": "x"}}]}, provider="ollama")
    assert fr("stop").stop_reason == "end_turn" and fr("length").stop_reason == "max_tokens"
    assert fr("content_filter").stop_reason == "content_filter" and fr("weird").stop_reason == "other"
    assert fr("stop").usage.input_tokens == 0


def test_openai_model_uses_injected_client():
    sent = {}

    class Resp:
        def model_dump(self):
            return {"id": "x", "model": "q", "choices": [{"finish_reason": "stop", "message": {"content": "hi"}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 1}}
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: (sent.update(kw), Resp())[1])))
    m = OpenAICompatModel("qwen3:8b", base_url="http://x", api_key="n", provider="ollama", client=client)
    r = m.complete(system="s", messages=[Message.user("yo")], weird_opt=1)
    assert r.text == "hi" and sent["messages"][0]["role"] == "system" and m.last_dropped_opts == ["weird_opt"]
    assert m.provider == "ollama" and m.model == "qwen3:8b"


def test_openai_direct_uses_max_completion_tokens_and_effort():
    req, _ = to_openai_request(model="gpt", system="", messages=[Message.user("x")], tools=None, max_tokens=9,
                               opts={"effort": "low", "parallel_tools": False}, provider="openai")
    assert req["max_completion_tokens"] == 9 and "max_tokens" not in req
    assert req["reasoning_effort"] == "low" and req["parallel_tool_calls"] is False


def test_anthropic_parallel_off_and_unsigned_thinking_dropped():
    msgs = [Message.user("x"), Message("assistant", [ThinkingBlock("t", provider="anthropic", provider_data={}),
                                                     ThinkingBlock("r", provider="openrouter")])]
    req, _ = to_anthropic_request(model="m", system="", messages=msgs, tools=None, max_tokens=5,
                                  opts={"parallel_tools": False})
    assert req["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert req["messages"][1]["content"] == [{"type": "text", "text": "(no content)"}], "never send an empty turn"


def test_openai_empty_assistant_turn_gets_empty_string():
    req, _ = to_openai_request(model="m", system="", messages=[Message("assistant", [ThinkingBlock("x", provider="anthropic")])],
                               tools=None, max_tokens=5, opts={}, provider="ollama")
    assert req["messages"][0] == {"role": "assistant", "content": ""}
