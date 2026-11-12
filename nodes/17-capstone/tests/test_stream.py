"""AGENT-OFF: assemble (YOU_DO task 2)."""
import copy

from agentlab.launch.stream import assemble
from agentlab.llm.types import TextBlock, ToolUseBlock

EVENTS = [
    {"type": "message_start", "id": "msg_1", "model": "claude-haiku-5-5"},
    {"type": "text_delta", "index": 0, "text": "Let me "},
    {"type": "tool_use_start", "index": 1, "id": "t1", "name": "lookup_order"},
    {"type": "text_delta", "index": 0, "text": "check."},
    {"type": "tool_input_delta", "index": 1, "partial_json": '{"order_'},
    {"type": "tool_input_delta", "index": 1, "partial_json": 'id": 4822}'},
    {"type": "block_stop", "index": 1},
    {"type": "ping"},
    {"type": "message_stop", "stop_reason": "tool_use",
     "usage": {"input_tokens": 800, "output_tokens": 40, "cache_read_tokens": 12, "surprise": 1}},
]


def test_text_and_tool_call():
    ev = copy.deepcopy(EVENTS)
    r = assemble(ev, provider="anthropic")
    assert r.content == [TextBlock("Let me check."), ToolUseBlock("t1", "lookup_order", {"order_id": 4822})]
    assert (r.stop_reason, r.id, r.model, r.provider) == ("tool_use", "msg_1", "claude-haiku-5-5", "anthropic")
    assert (r.usage.input_tokens, r.usage.output_tokens, r.usage.cache_read_tokens) == (800, 40, 12)
    assert r.raw_stop_reason == "tool_use" and r.latency_s == 0.0 and ev == EVENTS


def test_order_is_by_index_not_arrival():
    ev = [{"type": "tool_use_start", "index": 2, "id": "b", "name": "y"},
          {"type": "tool_use_start", "index": 1, "id": "a", "name": "x"},
          {"type": "text_delta", "index": 0, "text": "hi"},
          {"type": "message_stop", "stop_reason": "tool_use"}]
    r = assemble(ev, provider="p", model="fallback-name")
    assert [getattr(b, "id", None) for b in r.content] == [None, "a", "b"]
    assert r.content[1].input == {} and r.content[1].parse_error is None, "no arguments -> {}"
    assert r.model == "fallback-name" and r.usage.input_tokens == 0


def test_bad_arguments_and_empty_text():
    ev = [{"type": "text_delta", "index": 0, "text": ""},
          {"type": "tool_use_start", "index": 1, "id": "a", "name": "x"},
          {"type": "tool_input_delta", "index": 1, "partial_json": '{"a": '},
          {"type": "tool_use_start", "index": 2, "id": "b", "name": "y"},
          {"type": "tool_input_delta", "index": 2, "partial_json": '[1, 2]'},
          {"type": "message_stop", "stop_reason": "tool_use", "usage": {}}]
    a, b = assemble(ev, provider="p").content
    assert a.input == {} and a.raw_arguments == '{"a": ' and a.parse_error
    assert b.input == {} and b.raw_arguments == "[1, 2]" and b.parse_error


def test_a_cut_off_stream_never_yields_a_runnable_call():
    ev = EVENTS[:-2]                                    # no message_stop
    r = assemble(ev, provider="anthropic")
    assert r.stop_reason == "other"
    (call,) = [b for b in r.content if isinstance(b, ToolUseBlock)]
    assert call.parse_error and "ended" in call.parse_error, "even though its JSON happens to parse"
