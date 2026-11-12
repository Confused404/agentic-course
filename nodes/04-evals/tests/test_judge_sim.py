"""LLM judge and simulated user, driven by scripted models."""
import json

from agentlab.evals.graders import TrialContext, snapshot
from agentlab.evals.judge import JUDGE_SCHEMA, judge, render_evidence
from agentlab.evals.user_sim import SimulatedUser
from agentlab.llm.fake import ScriptedModel, fail, say
from agentlab.llm.types import Message, TextBlock, ToolResultBlock, ToolUseBlock


def c(conn):
    msgs = [Message.user("refund 4826"),
            Message("assistant", [ToolUseBlock("t1", "issue_refund", {"order_id": 4826})]),
            Message("user", [ToolResultBlock("t1", '{"status": "pending_approval"}' + "x" * 2000)]),
            Message("assistant", [TextBlock("Submitted for approval.")])]
    return TrialContext(conn, snapshot(conn), msgs, ["Submitted for approval."], 9006)


def test_evidence_rendering(conn):
    ev = render_evidence(c(conn))
    assert "CUSTOMER: refund 4826" in ev and "TOOL CALL issue_refund" in ev and "ASSISTANT: Submitted" in ev
    assert "pending_approval" in ev and len(ev) < 2000, "tool results are cut"
    long = render_evidence(c(conn), max_chars=200)
    assert "omitted" in long and len(long) < 400


def test_judge_verdicts_and_request_shape(conn):
    m = ScriptedModel([say(json.dumps({"reasoning": "says approval needed", "verdict": "pass"}))])
    r = judge(m, "honest about approval?", c(conn))
    assert r.verdict == "pass" and r.grader == "judge" and "approval" in r.detail
    sent = m.calls[0]
    assert sent["opts"]["json_schema"] == JUDGE_SCHEMA and list(JUDGE_SCHEMA["properties"])[0] == "reasoning"
    assert "RUBRIC" in sent["messages"][0].text and "TRANSCRIPT" in sent["messages"][0].text
    assert judge(ScriptedModel([say("not json")]), "x", c(conn)).verdict == "unknown"
    assert judge(ScriptedModel([say('{"reasoning": "?", "verdict": "unknown"}')]), "x", c(conn)).verdict == "unknown"
    assert judge(ScriptedModel([fail(RuntimeError("down"))]), "x", c(conn)).verdict == "unknown"


def test_simulated_user_flips_roles_and_stops():
    m = ScriptedModel([say("my order broke"), say("4821"), say("thanks [DONE]")])
    u = SimulatedUser(m, persona="vague", goal="refund", facts="order 4821")
    assert u.first_message() == "my order broke"
    assert u.reply("What's the order number?") == "4821"
    second_call = m.calls[1]["messages"]
    assert second_call[-1].role == "user" and "order number" in second_call[-1].text, "agent replies are the sim's 'user'"
    assert u.reply("Refunded!") is None
    assert "vague" in m.calls[0]["system"] and "4821" in m.calls[0]["system"]


def test_simulated_user_turn_cap():
    u = SimulatedUser(ScriptedModel([say("a")] * 10), persona="p", goal="g", max_turns=2)
    u.first_message()
    assert u.reply("x") == "a" and u.reply("y") is None
