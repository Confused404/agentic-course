"""Support tools (bound to the session) and the assistant, with a scripted model."""
import json


from agentlab.assistant.support import SupportAssistant
from agentlab.assistant.tools import make_support_tools, search_help_center
from agentlab.llm.fake import ScriptedModel, call, say
from agentlab.llm.types import ToolUseBlock


def run_tool(reg, name, **kw):
    return reg.execute(ToolUseBlock("t", name, kw))


def test_tool_set_and_schemas(conn):
    reg = make_support_tools(conn, 9001)
    assert reg.names() == sorted(["get_my_orders", "lookup_order", "check_refund_eligibility", "issue_refund",
                                  "cancel_order", "escalate_to_human", "search_help_center"])
    for spec in reg.specs():
        props = spec.input_schema.get("properties", {})
        assert "customer_id" not in props, "identity comes from the session, not the model"
        assert spec.input_schema.get("additionalProperties") is False
        assert len(spec.description) > 20


def test_tools_are_bound_to_the_customer(conn):
    jane = make_support_tools(conn, 9004)
    r = run_tool(jane, "lookup_order", order_id=4829)            # the other Jane's order
    assert r.is_error and json.loads(r.content)["error"] == "NOT_FOUND"
    r = run_tool(jane, "issue_refund", order_id=4829, amount_cents=100, reason="changed_mind")
    assert r.is_error
    assert conn.execute("SELECT count(*) FROM refunds WHERE order_id=4829").fetchone()[0] == 0


def test_refund_records_actor(conn):
    reg = make_support_tools(conn, 9001, actor="agent:test")
    r = run_tool(reg, "issue_refund", order_id=4822, amount_cents=4899, reason="changed_mind")
    assert not r.is_error and json.loads(r.content)["status"] == "issued"
    assert conn.execute("SELECT actor FROM refunds WHERE order_id=4822").fetchone()[0] == "agent:test"


def test_search_help_center_scores_and_includes_archived():
    hits = search_help_center("refund window days return")
    assert hits and hits[0]["slug"] in ("refund-policy", "returns-policy-2025")
    assert {"slug", "title", "status", "updated", "excerpt"} <= set(hits[0])
    assert any(h["status"] == "archived" for h in search_help_center("returns restocking fee 14 days"))
    assert search_help_center("zzzz qqqq") == []
    assert "---" not in hits[0]["excerpt"][:5]


def test_assistant_refund_flow_changes_db_and_keeps_history(conn):
    model = ScriptedModel([
        call("check_refund_eligibility", order_id=4822, reason="changed_mind"),
        call("issue_refund", order_id=4822, amount_cents=4899, reason="changed_mind"),
        say("Done: $48.99 refunded."),
        say("You're welcome!"),
    ])
    a = SupportAssistant(model, conn, customer_id=9001)
    r1 = a.chat("refund 4822 please")
    assert r1.reply == "Done: $48.99 refunded." and r1.result.stop == "end_turn"
    assert conn.execute("SELECT status FROM refunds WHERE order_id=4822").fetchone()[0] == "issued"
    r2 = a.chat("thanks")
    assert r2.reply == "You're welcome!"
    assert len(model.calls[3]["messages"]) == 7, "second chat() sees the whole history"
    assert "2026-11-01" in model.calls[0]["system"], "today's date from shopfront.clock"


def test_assistant_never_returns_empty_reply(conn):
    a = SupportAssistant(ScriptedModel([call("get_my_orders")] * 2 + [say("yes, here")]), conn, customer_id=9001, max_turns=2)
    r = a.chat("hi")
    assert r.result.stop == "max_turns" and r.reply.strip()
    assert "noted" not in r.reply.lower(), "don't claim something was recorded when nothing was"
    r2 = a.chat("still there?")      # history must still be a valid transcript after a stopped run
    assert r2.reply.strip()
