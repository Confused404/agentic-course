"""parse.py: pure functions over recorded payloads, including broken ones."""
import json
from pathlib import Path

from agentlab.probe.parse import parse_anthropic, parse_openai

FX = Path(__file__).parent / "fixtures"
load = lambda n: json.loads((FX / n).read_text())  # noqa: E731


def test_anthropic_text_tools_usage():
    p = parse_anthropic(load("anthropic_tool_use.json"))
    assert p["text"] == "Let me look that up."
    assert [c["name"] for c in p["tool_calls"]] == ["lookup_order", "lookup_order"]
    assert p["tool_calls"][0]["arguments"] == {"order_id": 4821}
    assert p["tool_calls"][0]["raw_arguments"] is None and p["tool_calls"][0]["parse_error"] is None
    assert p["stop_reason"] == "tool_use"
    u = p["usage"]
    assert (u.input_tokens, u.output_tokens, u.cache_read_tokens, u.cache_write_tokens) == (312, 88, 1024, 0)
    assert u.reasoning_tokens == 52, "thinking tokens come from usage.output_tokens_details"


def test_openai_arguments_are_strings_and_can_be_broken():
    p = parse_openai(load("openai_tool_calls.json"))
    good, bad = p["tool_calls"]
    assert good["arguments"] == {"order_id": 4821} and good["raw_arguments"] == '{"order_id": 4821}'
    assert bad["arguments"] is None and bad["parse_error"], "invalid JSON must be captured, not raised"
    assert p["text"] == ""


def test_openai_usage_cached_reasoning_cost():
    u = parse_openai(load("openai_tool_calls.json"))["usage"]
    assert u.input_tokens == 372 and u.cache_read_tokens == 128      # 500 - 128 cached
    assert u.output_tokens == 40 and u.reasoning_tokens == 16
    assert abs(u.cost_usd - 0.000154) < 1e-12


def test_local_runtime_says_stop_but_called_a_tool():
    p = parse_openai(load("ollama_stop_with_tools.json"))
    assert p["stop_reason"] == "tool_calls"
    call = p["tool_calls"][0]
    assert call["arguments"] is None and call["parse_error"], "a JSON array is not an arguments object"


def test_missing_usage_and_truncation():
    p = parse_openai(load("openai_text_only_no_usage.json"))
    assert p["stop_reason"] == "length" and p["text"] == "Your order"
    assert p["usage"].input_tokens == 0 and p["usage"].output_tokens == 0


def test_no_argument_tool_is_not_an_error():
    p = parse_openai({"choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [
        {"id": "c", "type": "function", "function": {"name": "list_open_tickets", "arguments": ""}}]}}]})
    assert p["tool_calls"][0]["arguments"] == {} and p["tool_calls"][0]["parse_error"] is None
