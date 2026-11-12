"""AGENT-OFF code under test: your run_agent (agentlab/agent/loop.py). Uses a tiny local tool executor so these
tests don't depend on the coding agent's ToolRegistry."""
import json


from agentlab.agent.loop import LoopConfig, run_agent
from agentlab.costs import Budget
from agentlab.llm.fake import ScriptedModel, bad_call, call, calls, last_tool_results, say, think, truncated
from agentlab.llm.types import (Message, ModelResponse, TextBlock, ThinkingBlock, ToolResultBlock, ToolSpec,
                                ToolUseBlock, Usage)


class Tools:
    """Minimal ToolExecutor: add(a, b) and boom()."""
    def __init__(self):
        self.executed = []

    def specs(self):
        return [ToolSpec("add", "add two ints", {"type": "object", "properties": {"a": {"type": "integer"},
                                                                                   "b": {"type": "integer"}}}),
                ToolSpec("boom", "always fails", {"type": "object", "properties": {}})]

    def execute(self, c: ToolUseBlock) -> ToolResultBlock:
        self.executed.append((c.name, c.input))
        if c.name == "add":
            return ToolResultBlock(c.id, str(c.input["a"] + c.input["b"]))
        return ToolResultBlock(c.id, "boom failed", is_error=True)


def run(script, msgs=None, **cfg):
    m = ScriptedModel(script)
    t = Tools()
    res = run_agent(m, "sys", msgs or [Message.user("hi")], t, LoopConfig(**cfg))
    return res, m, t


def test_no_tools_single_turn():
    res, m, _ = run([say("hello")])
    assert res.stop == "end_turn" and res.final_text == "hello" and res.turns == 1
    assert [x.role for x in res.messages] == ["user", "assistant"]
    assert m.calls[0]["tools"] == ["add", "boom"] and m.calls[0]["system"] == "sys"


def test_tool_round_trip_and_pairing():
    res, m, t = run([call("add", a=2, b=3), say("5")])
    assert t.executed == [("add", {"a": 2, "b": 3})]
    tool_msg = res.messages[2]
    assert tool_msg.role == "user" and isinstance(tool_msg.content[0], ToolResultBlock)
    assert tool_msg.content[0].tool_use_id == res.messages[1].content[0].id
    assert tool_msg.content[0].content == "5"
    assert res.final_text == "5" and res.turns == 2
    assert [r.name for r in res.tool_calls] == ["add"] and not res.tool_calls[0].is_error


def test_parallel_calls_one_message_in_order():
    res, _, t = run([calls(("add", {"a": 1, "b": 1}), ("boom", {}), ("add", {"a": 2, "b": 2})), say("ok")])
    results = res.messages[2].content
    assert len(results) == 3 and all(isinstance(b, ToolResultBlock) for b in results)
    assert [b.tool_use_id for b in results] == [b.id for b in res.messages[1].content]
    assert [b.is_error for b in results] == [False, True, False]
    assert len(res.messages) == 4, "all results go in ONE user message"


def test_parse_error_is_not_executed_and_is_reported():
    res, m, t = run([bad_call("add", '{"a": 1, "b": '), say("sorry")])
    assert t.executed == []
    r = res.messages[2].content[0]
    assert r.is_error and "json" in r.text.lower()
    assert res.tool_calls[0].is_error


def test_max_turns():
    res, m, _ = run([call("add", a=1, b=1)] * 3, max_turns=3)
    assert res.stop == "max_turns" and res.turns == 3 and len(m.calls) == 3
    assert isinstance(res.messages[-1].content[0], ToolResultBlock), "last calls still get results"


def test_truncated_tool_call_is_not_executed_but_transcript_stays_valid():
    r = call("add", a=1, b=1)
    r.stop_reason = "max_tokens"
    res, _, t = run([r])
    assert res.stop == "max_tokens" and t.executed == []
    last = res.messages[-1]
    assert last.role == "user" and last.content[0].is_error and "not executed" in last.content[0].text.lower()
    assert last.content[0].tool_use_id == res.messages[-2].content[0].id


def test_transcript_is_resumable_after_any_stop():
    """A stopped run's transcript must be valid input for the next run (no unanswered tool calls)."""
    big = call("add", a=1, b=1)
    big.usage = Usage(input_tokens=1_000_000)
    res, _, _ = run([big], budget=Budget(limit_usd=5))
    assert res.stop == "budget"
    for i, m in enumerate(res.messages):
        calls_ = [b.id for b in m.content if isinstance(b, ToolUseBlock)]
        if calls_:
            nxt = res.messages[i + 1]
            assert [b.tool_use_id for b in nxt.content if isinstance(b, ToolResultBlock)] == calls_


def test_budget_checked_before_calling():
    b = Budget(limit_usd=1)
    b.spent_usd = 2.0                       # already over (e.g. an earlier conversation in this session)
    res, m, _ = run([say("x")], budget=b)
    assert res.stop == "budget" and len(m.calls) == 0, "no paid call once the cap is reached"


def test_tool_use_without_calls_is_other():
    weird = ModelResponse([TextBlock("hmm")], "tool_use", Usage(1, 1), "m", "fake")
    res, _, _ = run([weird])
    assert res.stop == "other" and res.messages[-1].role == "assistant"


def test_max_tokens_text_and_refusal():
    assert run([truncated("Your ord")])[0].stop == "max_tokens"
    refusal = ModelResponse([TextBlock("no")], "refusal", Usage(1, 1), "m", "fake")
    assert run([refusal])[0].stop == "refusal"


def test_pause_turn_continues_without_user_message():
    p = ModelResponse([TextBlock("working...")], "pause_turn", Usage(1, 1), "m", "fake")
    res, m, _ = run([p, say("done")])
    assert res.stop == "end_turn" and len(m.calls) == 2
    assert [x.role for x in res.messages] == ["user", "assistant", "assistant"]


def test_thinking_blocks_kept_verbatim():
    res, m, _ = run([think("plan: add", call("add", a=1, b=2)), say("3")])
    first = res.messages[1].content[0]
    assert isinstance(first, ThinkingBlock) and first.provider_data["signature"].startswith("sig-")
    sent_back = m.calls[1]["messages"][1].content[0]
    assert isinstance(sent_back, ThinkingBlock), "reasoning must be sent back on the next turn"


def test_does_not_mutate_input():
    msgs = [Message.user("hi")]
    res, _, _ = run([call("add", a=1, b=1), say("2")], msgs=msgs)
    assert len(msgs) == 1 and len(res.messages) == 4


def test_usage_summed_and_budget_stop():
    u = Usage(input_tokens=1_000_000, output_tokens=0)
    big = call("add", a=1, b=1)
    big.usage = u
    res, _, _ = run([big, say("x")], budget=Budget(limit_usd=1000))
    assert res.usage.input_tokens == 1_000_000 + 100
    # fake model "scripted" is unpriced -> charged at the fail-closed fallback ($10/M input)
    res2, m2, _ = run([big, say("x")], budget=Budget(limit_usd=5))
    assert res2.stop == "budget" and len(m2.calls) == 1 and res2.cost_usd >= 5


def test_model_opts_passed_through():
    _, m, _ = run([say("x")], model_opts={"effort": "low"}, max_tokens=777)
    assert m.calls[0]["opts"] == {"effort": "low"} and m.calls[0]["max_tokens"] == 777


def test_callable_step_sees_tool_results():
    def echo(system, messages, tools, opts):
        return say("result was " + last_tool_results(messages)[0].text)
    res, _, _ = run([call("add", a=20, b=22), echo])
    assert res.final_text == "result was 42"


def test_trace_has_agent_chat_and_tool_spans():
    import agentlab.config as cfg
    run([call("add", a=1, b=1), say("2")], agent_name="trace-test")
    spans = [json.loads(line) for f in (cfg.RUNS / "traces").glob("*.jsonl") for line in f.read_text().splitlines()]
    names = [s["name"] for s in spans]
    assert "invoke_agent trace-test" in names and "execute_tool add" in names
    assert sum(n.startswith("chat ") for n in names) == 2
    root = next(s for s in spans if s["name"] == "invoke_agent trace-test")
    assert all(s["parent_id"] == root["span_id"] for s in spans if s["name"].startswith(("chat", "execute_tool")))
