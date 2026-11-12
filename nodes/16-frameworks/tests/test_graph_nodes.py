"""AGENT-OFF: tools_node (YOU_DO task 3). Uses a real LangGraph graph so the resume semantics are real."""
import copy
import operator
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from agentlab.frameworks.graph_nodes import tools_node
from agentlab.llm.types import Message, TextBlock, ToolResultBlock, ToolUseBlock, to_dict


class Reg:
    def __init__(self):
        self.ran = []

    def execute(self, call):
        self.ran.append(call.name)
        return ToolResultBlock(call.id, f"{call.name} ok")


def turn(*calls):
    blocks = [ToolUseBlock(cid, name, args, raw_arguments=raw, parse_error=err)
              for cid, name, args, raw, err in calls]
    return {"messages": [to_dict(Message.user("hi")), to_dict(Message("assistant", blocks))]}


def C(cid, name, args=None, raw=None, err=None):
    return (cid, name, args or {}, raw, err)


def test_no_calls():
    assert tools_node({"messages": [to_dict(Message.user("x"))]}, registry=Reg()) == {"messages": []}
    assert tools_node({"messages": [to_dict(Message("assistant", [TextBlock("hi")]))]}, registry=Reg()) == \
        {"messages": []}


def test_plain_execution_in_order_without_interrupt():
    reg, asked = Reg(), []
    st = turn(C("a", "lookup_order"), C("b", "get_my_orders"), C("c", "lookup_order", raw="{", err="bad"))
    before = copy.deepcopy(st)
    out = tools_node(st, registry=reg, approval_tools={"issue_refund"}, interrupt=asked.append)
    (m,) = out["messages"]
    res = Message.from_dict(m)
    assert res.role == "user" and [b.tool_use_id for b in res.content] == ["a", "b", "c"]
    assert reg.ran == ["lookup_order", "get_my_orders"] and res.content[2].is_error, "unparsed: never executed"
    assert asked == [] and st == before


def test_one_interrupt_before_anything_runs():
    reg, asked = Reg(), []

    def interrupt(payload):
        asked.append(payload)
        assert reg.ran == [], "nothing may run before the approval"
        return {"r1": {"approved": False, "by": "maria", "note": "over limit"}, "r2": True}
    st = turn(C("x", "lookup_order"), C("r1", "issue_refund", {"order_id": 1}), C("c", "cancel_order"),
              C("r2", "issue_refund", {"order_id": 2}), C("r3", "issue_refund"))
    res = Message.from_dict(tools_node(st, registry=reg, approval_tools={"issue_refund"},
                                       interrupt=interrupt)["messages"][0])
    assert len(asked) == 1 and [a["call_id"] for a in asked[0]["approvals"]] == ["r1", "r2", "r3"]
    assert asked[0]["approvals"][0] == {"call_id": "r1", "tool": "issue_refund", "args": {"order_id": 1}}
    texts = {b.tool_use_id: b for b in res.content}
    assert texts["r1"].is_error and texts["r1"].text == "Denied by maria: over limit"
    assert texts["r3"].is_error and "a human" in texts["r3"].text, "no decision = denied"
    assert reg.ran == ["lookup_order", "cancel_order", "issue_refund"]


def test_side_effects_run_once_across_a_real_resume():
    reg = Reg()

    class S(TypedDict):
        messages: Annotated[list, operator.add]
    g = StateGraph(S)
    g.add_node("tools", lambda s: tools_node(s, registry=reg, approval_tools={"issue_refund"}))
    g.add_edge(START, "tools")
    g.add_edge("tools", END)
    app = g.compile(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "t"}}
    app.invoke(turn(C("c", "cancel_order"), C("r", "issue_refund")), cfg)
    assert reg.ran == [], "paused before anything ran"
    out = app.invoke(Command(resume={"r": True}), cfg)
    assert reg.ran == ["cancel_order", "issue_refund"], "after the resume, each side effect ran exactly once"
    assert Message.from_dict(out["messages"][-1]).content[1].text == "issue_refund ok"
