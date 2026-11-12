"""Pydantic AI messages -> the course's neutral Messages. AGENT-OFF: written by hand in Node 16 YOU_DO task 2.

Why it matters: the Node 04 graders (and your traces, evals and cost reports) read the course's Message format. A
framework port is only comparable if its conversation converts faithfully: same tool calls, same ids, same errors,
same order. Tests: nodes/16-frameworks/tests/test_convert.py. Read TEXTBOOK §3 first.
"""
from __future__ import annotations

import json  # noqa: F401 - you will need it

from pydantic_ai.messages import (ModelRequest, ModelResponse, RetryPromptPart, TextPart,  # noqa: F401
                                  ThinkingPart, ToolCallPart, ToolReturnPart, UserPromptPart)

from agentlab.llm.types import Message, TextBlock, ToolResultBlock, ToolUseBlock  # noqa: F401

ERROR_PREFIX = "ERROR: "      # how the ports mark a business error returned by a tool (see pydantic_port)


def to_course_messages(messages: list) -> list[Message]:
    """Convert a Pydantic AI message list (ModelRequest / ModelResponse objects, in order) to course Messages.
    Contract (each line is tested):

    1. ModelResponse -> an "assistant" Message: TextPart -> TextBlock(content) (skip empty text); ToolCallPart ->
       ToolUseBlock(tool_call_id, tool_name, args), where args may be a dict, a JSON string or None. A JSON string
       that parses to a dict -> that dict; None or "" -> {}; anything else -> input {} with raw_arguments=<the
       string> and parse_error=<a short message>. Other parts (ThinkingPart, ...) are skipped.
    2. ModelRequest -> a "user" Message: first a ToolResultBlock per ToolReturnPart and per RetryPromptPart that has
       a tool_name (in part order), then a TextBlock per UserPromptPart with str content (non-str content: skip).
       Other parts (system prompt, instructions) are skipped: the system prompt lives outside the transcript.
    3. ToolReturnPart -> ToolResultBlock(tool_call_id, text, is_error): text = content if it's a str, else
       json.dumps(content, default=str); is_error if part.outcome is not "success", or the text starts with
       ERROR_PREFIX (then the prefix is removed from the text).
       (A retry that answers a tool call arrives as a ToolReturnPart with outcome "retried": an error, by the rule
       above.) RetryPromptPart, deprecated in Pydantic AI 2.x but still found in stored histories: with a
       tool_name -> ToolResultBlock(tool_call_id, <its content as text: a str as is, a list of error details as
       json.dumps>, is_error=True); without one -> skipped (like RetryFeedbackPart and other parts).
    4. A message that ends up with no blocks is dropped. Consecutive messages with the same role are merged into
       one (blocks in order), so the result alternates user/assistant like a course transcript.
    5. Never mutate the inputs.
    """
    raise NotImplementedError("AGENT-OFF: Node 16 YOU_DO task 2")
