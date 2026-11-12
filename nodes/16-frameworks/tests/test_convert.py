"""AGENT-OFF: to_course_messages (YOU_DO task 2)."""
import copy

import pytest

from pydantic_ai.messages import (ModelRequest, ModelResponse, RetryPromptPart, SystemPromptPart, TextPart,
                                  ThinkingPart, ToolCallPart, ToolReturnPart, UserPromptPart)

from agentlab.frameworks.convert import to_course_messages
from agentlab.llm.types import TextBlock, ToolResultBlock, ToolUseBlock


def test_a_tool_round_trip():
    msgs = [ModelRequest([SystemPromptPart("sys"), UserPromptPart("where is 4822?")]),
            ModelResponse([ThinkingPart("hmm"), TextPart("Checking."),
                           ToolCallPart("lookup_order", {"order_id": 4822}, "c1")]),
            ModelRequest([ToolReturnPart("lookup_order", '{"status": "shipped"}', "c1")]),
            ModelResponse([TextPart("It shipped.")])]
    before = copy.deepcopy(msgs)
    out = to_course_messages(msgs)
    assert [m.role for m in out] == ["user", "assistant", "user", "assistant"]
    assert out[0].content == [TextBlock("where is 4822?")], "system prompt skipped"
    assert out[1].content[0] == TextBlock("Checking.") and len(out[1].content) == 2, "thinking skipped"
    call = out[1].content[1]
    assert isinstance(call, ToolUseBlock) and (call.id, call.name, call.input) == ("c1", "lookup_order",
                                                                                  {"order_id": 4822})
    assert out[2].content == [ToolResultBlock("c1", '{"status": "shipped"}', False)]
    assert msgs == before


def test_argument_forms():
    out = to_course_messages([ModelResponse([ToolCallPart("a", '{"x": 1}', "1"), ToolCallPart("b", None, "2"),
                                             ToolCallPart("c", "", "3"), ToolCallPart("d", "{oops", "4"),
                                             ToolCallPart("e", "[1, 2]", "5")])])
    a, b, c, d, e = out[0].content
    assert a.input == {"x": 1} and b.input == {} and c.input == {} and not (a.parse_error or b.parse_error)
    assert d.input == {} and d.raw_arguments == "{oops" and d.parse_error
    assert e.input == {} and e.parse_error, "valid JSON that isn't an object"


@pytest.mark.filterwarnings("ignore:.*RetryPromptPart")
def test_errors_and_retries():
    out = to_course_messages([ModelRequest([
        ToolReturnPart("issue_refund", "ERROR: Refund not allowed", "c1"),
        ToolReturnPart("cancel_order", {"status": "cancelled"}, "c2"),
        ToolReturnPart("issue_refund", "nope", "c3", outcome="denied"),
        RetryPromptPart("bad args", tool_name="lookup_order", tool_call_id="c4"),
        RetryPromptPart("output invalid"),
        ToolReturnPart("lookup_order", "Validation failed: order_id must be an integer", "c5", outcome="retried"),
        UserPromptPart("also, thanks")])])
    (m,) = out
    r1, r2, r3, r4, r5, t = m.content
    assert r5.is_error and r5.tool_use_id == "c5", "a retry answering a tool call is an error result"
    assert r1 == ToolResultBlock("c1", "Refund not allowed", True), "the ERROR prefix marks a business error"
    assert r2.text == '{"status": "cancelled"}' and not r2.is_error
    assert r3.is_error and r4 == ToolResultBlock("c4", "bad args", True)
    assert t == TextBlock("also, thanks"), "results first, then the user's text"


def test_merging_and_dropping():
    out = to_course_messages([ModelRequest([UserPromptPart("a")]), ModelRequest([SystemPromptPart("s")]),
                              ModelRequest([UserPromptPart("b")]), ModelResponse([TextPart("")]),
                              ModelResponse([TextPart("x")]), ModelResponse([TextPart("y")])])
    assert [(m.role, [b.text for b in m.content]) for m in out] == [("user", ["a", "b"]), ("assistant", ["x", "y"])]
    assert to_course_messages([]) == []


@pytest.mark.filterwarnings("ignore:.*RetryPromptPart")
def test_structured_retry_content_and_non_text_prompts():
    from pydantic_ai.messages import BinaryContent
    details = [{"type": "int_parsing", "loc": ["order_id"], "msg": "not an int", "input": "x"}]
    (m,) = to_course_messages([ModelRequest([RetryPromptPart(details, tool_name="lookup_order", tool_call_id="c"),
                                             UserPromptPart([BinaryContent(b"x", media_type="image/png")])])])
    (r,) = m.content
    assert r.is_error and "int_parsing" in r.text, "a list of error details is passed on as JSON"
