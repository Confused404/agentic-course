import json

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from agentlab.llm import fake
from agentlab.llm.types import ToolResultBlock, ToolUseBlock


def refunding_function(order_id=4822):
    """A Pydantic AI FunctionModel 'model': eligibility -> refund the max -> answer, from the messages alone."""
    def f(messages, info: AgentInfo):
        rets = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        u = RequestUsage(input_tokens=1000, output_tokens=20, cache_read_tokens=400)
        if not rets:
            return ModelResponse([ToolCallPart("check_refund_eligibility",
                                               {"order_id": order_id, "reason": "changed_mind"})], usage=u)
        if rets[-1].tool_name == "check_refund_eligibility":
            amt = json.loads(rets[-1].content).get("max_refundable_cents") or 1
            return ModelResponse([ToolCallPart("issue_refund", {"order_id": order_id, "amount_cents": amt,
                                                                "reason": "changed_mind"})], usage=u)
        return ModelResponse([TextPart("Done: " + str(rets[-1].content)[:60])], usage=u)
    return FunctionModel(f, model_name="claude-haiku-5-5")


def _refunds(conn, order=4822):
    return conn.execute("SELECT COUNT(*) FROM refunds WHERE order_id = ?", (order,)).fetchone()[0]


def test_pydantic_port_speaks_the_eval_contract(conn, needs_convert):
    from agentlab.costs import Budget
    from agentlab.frameworks.pydantic_port import PydanticSupportAssistant, course_usage
    b = Budget(limit_usd=1.0)
    a = PydanticSupportAssistant(refunding_function(), conn, 9001, b, price_model="claude-haiku-5-5")
    r = a.chat("I changed my mind about 4822, refund it")
    assert r.result.stop == "end_turn" and r.reply.startswith("Done") and r.result.turns == 3
    assert _refunds(conn) == 1 and b.calls == 3 and b.spent_usd > 0
    roles = [m.role for m in a.transcript]
    assert roles[0] == "user" and roles[-1] == "assistant" and a.transcript[0].text.startswith("I changed")
    calls = [x.name for m in a.transcript for x in m.content if isinstance(x, ToolUseBlock)]
    assert calls == ["check_refund_eligibility", "issue_refund"]
    u = course_usage(RequestUsage(input_tokens=1000, output_tokens=5, cache_read_tokens=400, cache_write_tokens=100))
    assert (u.input_tokens, u.cache_read_tokens, u.total_input) == (500, 400, 1000)
    assert course_usage(RequestUsage(input_tokens=10, cost=0.5)).cost_usd is None, "Pydantic AI's estimate ignored"
    assert course_usage(RequestUsage(input_tokens=10), {"cost": 0.002}).cost_usd == 0.002, "provider-reported cost"
    per_call = (600 * 0.10 + 400 * 0.01 + 20 * 0.50) / 1e6
    assert b.spent_usd == pytest.approx(3 * per_call), "priced from the course table, cache reads at the cache rate"


def test_two_chats_charge_and_record_each_response_once(conn, needs_convert):
    from agentlab.costs import Budget
    from agentlab.frameworks.pydantic_port import PydanticSupportAssistant
    b = Budget(limit_usd=1.0)
    a = PydanticSupportAssistant(refunding_function(), conn, 9001, b, price_model="claude-haiku-5-5")
    a.chat("refund 4822 please")
    n_blocks = sum(len(m.content) for m in a.transcript)
    r = a.chat("thanks!")
    assert b.calls == 3 + r.result.turns and r.result.turns >= 1
    added = sum(len(m.content) for m in a.transcript) - n_blocks
    assert added <= 1 + 2 * r.result.turns, "only the new part of the run is appended"
    assert [x.name for m in a.transcript for x in m.content if isinstance(x, ToolUseBlock)].count("issue_refund") == 1


def test_pydantic_port_limits_and_errors(conn, needs_convert):
    from agentlab.frameworks.pydantic_port import PydanticSupportAssistant

    def loop(messages, info):
        return ModelResponse([ToolCallPart("lookup_order", {"order_id": 999999})])
    from agentlab.costs import Budget
    b = Budget(limit_usd=1.0)
    a = PydanticSupportAssistant(FunctionModel(loop, model_name="m"), conn, 9001, b, max_requests=3,
                                 price_model="claude-haiku-5-5")
    r = a.chat("where?")
    assert r.result.stop == "max_turns" and r.result.turns == 3 and "Sorry" in r.reply
    assert b.calls == 3, "requests made before the limit are charged"
    errs = [x for m in a.transcript for x in m.content if isinstance(x, ToolResultBlock)]
    assert errs and all(e.is_error for e in errs), "business errors reach the transcript as errors"


def test_budget_is_enforced_per_request(conn, needs_convert):
    from agentlab.costs import Budget, BudgetExceeded
    from agentlab.frameworks.pydantic_port import PydanticSupportAssistant
    b = Budget(limit_usd=0.0001)
    a = PydanticSupportAssistant(refunding_function(), conn, 9001, b, price_model="claude-haiku-5-5")
    with pytest.raises(BudgetExceeded):
        a.chat("refund 4822")
    # each response costs $0.000074: the 2nd crosses the cap, and the run stops before its refund call runs
    assert b.calls == 2 and _refunds(conn) == 0, "stopped at the response that crossed the cap, before its tools"
    assert a.transcript and a.transcript[0].role == "user", "the failed turn is still in the transcript"


def test_tools_of_one_response_run_in_order(conn, needs_convert):
    from agentlab.frameworks.pydantic_port import PydanticSupportAssistant
    order = []

    def two(messages, info):
        if any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
            return ModelResponse([TextPart("ok")])
        return ModelResponse([ToolCallPart("lookup_order", {"order_id": 4822}, "a"),
                              ToolCallPart("get_my_orders", {}, "b")])
    a = PydanticSupportAssistant(FunctionModel(two, model_name="m"), conn, 9001)
    for name in ("lookup_order", "get_my_orders"):
        t = a.registry.get(name)
        orig = t.fn
        t.fn = (lambda _o=orig, _n=name: (lambda **kw: (order.append(_n + ":start"), _o(**kw),
                                                       order.append(_n + ":end"))[1]))()
    a.chat("orders?")
    assert order == ["lookup_order:start", "lookup_order:end", "get_my_orders:start", "get_my_orders:end"]


def test_pydantic_deferred_approval(conn):
    """Pydantic AI's own human-in-the-loop: the run ends with DeferredToolRequests; you resume with results."""
    from pydantic_ai import DeferredToolRequests, DeferredToolResults
    from agentlab.assistant.tools import make_support_tools
    from agentlab.frameworks.pydantic_port import build_agent, dump_history, load_history
    agent = build_agent(refunding_function(), make_support_tools(conn, 9001, variant="v2"), "sys",
                        approval_tools=frozenset({"issue_refund"}))
    r = agent.run_sync("refund 4822")
    assert isinstance(r.output, DeferredToolRequests) and _refunds(conn) == 0
    (call,) = r.output.approvals
    saved = dump_history(r.all_messages())                    # what you'd persist while a person decides
    r2 = agent.run_sync(message_history=load_history(saved),
                        deferred_tool_results=DeferredToolResults(approvals={call.tool_call_id: True}))
    assert isinstance(r2.output, str) and r2.output.startswith("Done") and _refunds(conn) == 1


class GraphRefunder:
    """A stateless course ChatModel: eligibility -> refund -> answer, ids derived from the transcript."""
    provider, model = "fake", "claude-haiku-5-5"

    def __init__(self):
        self.calls = 0

    def complete(self, *, messages, **kw):
        self.calls += 1
        res = [b for m in messages if m.role == "user" for b in m.content if isinstance(b, ToolResultBlock)]
        if not res:
            r = fake.call("check_refund_eligibility", order_id=4826, reason="not_as_described")
        elif len(res) == 1:
            amt = json.loads(res[-1].text).get("max_refundable_cents") or 1
            r = fake.call("issue_refund", order_id=4826, amount_cents=amt, reason="not_as_described")
        else:
            r = fake.say("Result: " + res[-1].text[:60])
        for i, b in enumerate(r.tool_calls):
            b.id = f"g{len(res)}_{i}"
        return r


def test_graph_port_runs_and_pauses_across_processes(conn, tmp_path, needs_nodes):
    from agentlab.frameworks.graph_port import GraphSupportAssistant, sqlite_checkpointer
    cp = tmp_path / "cp.db"
    m = GraphRefunder()
    g = GraphSupportAssistant(m, conn, 9006, checkpointer=sqlite_checkpointer(cp),
                              approval_tools=frozenset({"issue_refund"}), thread_id="t1")
    r = g.chat("refund 4826 please")
    assert r.result.stop == "awaiting_approval" and _refunds(conn, 4826) == 0
    (p,) = g.pending_approvals()
    assert p["tool"] == "issue_refund"
    g2 = GraphSupportAssistant(m, conn, 9006, checkpointer=sqlite_checkpointer(cp),      # "another process"
                               approval_tools=frozenset({"issue_refund"}), thread_id="t1")
    assert g2.pending_approvals() == [p]
    assert g2.chat("hello?").result.stop == "awaiting_approval" and m.calls == 2, "no new turn while waiting"
    r = g2.resume({p["call_id"]: {"approved": True, "by": "maria"}})
    assert r.result.stop == "end_turn" and r.reply.startswith("Result") and _refunds(conn, 4826) == 1
    assert m.calls == 3 and r.result.turns == 1 and r.result.usage.input_tokens == 100


def test_graph_port_turn_cap(conn, needs_nodes):
    from agentlab.frameworks.graph_port import GraphSupportAssistant

    class Looper:
        provider, model, n = "fake", "m", 0

        def complete(self, **kw):
            Looper.n += 1
            r = fake.call("lookup_order", order_id=4822)
            r.tool_calls[0].id = f"l{Looper.n}"
            return r
    g = GraphSupportAssistant(Looper(), conn, 9001, max_calls=3)
    r = g.chat("loop")
    assert r.result.stop == "max_turns" and r.result.turns == 3 and "Sorry" in r.reply
    r = g.chat("again")
    assert r.result.turns == 3, "the cap is per customer message"
