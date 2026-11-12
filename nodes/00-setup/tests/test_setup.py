"""Node 00 grader: is the course infrastructure working on this machine? (offline)"""
import pytest

from agentlab import tracing
from agentlab.config import ROOT, resolve
from agentlab.costs import Budget, BudgetExceeded, compute_cost
from agentlab.llm.fake import ScriptedModel, ScriptExhausted, call, say
from agentlab.llm.types import ChatModel, Message, Usage


def test_database_seeded():
    assert (ROOT / "data" / "shopfront.db").exists(), "run `make seed`"
    assert len(list((ROOT / "data" / "help_center").glob("*.md"))) >= 20


def test_aliases_resolve():
    for alias in ("fast", "mid", "gpt-fast", "local"):
        provider, model = resolve(alias)
        assert provider and model


def test_budget_is_a_hard_cap():
    b = Budget(limit_usd=0.001, label="test")
    b.charge("claude-haiku-5-5", Usage(input_tokens=1000, output_tokens=100))   # tiny
    with pytest.raises(BudgetExceeded):
        b.charge("claude-haiku-5-5", Usage(input_tokens=1_000_000, output_tokens=0))


def test_long_context_pricing_tier():
    short = compute_cost("claude-haiku-5-5", Usage(input_tokens=100_000))
    long = compute_cost("claude-haiku-5-5", Usage(input_tokens=100_001))
    assert long > 4 * short, "prompts over the threshold are billed at the long-context rate"


def test_fake_model_is_a_chat_model():
    m = ScriptedModel([call("lookup_order", order_id=1), say("done")])
    assert isinstance(m, ChatModel)
    r1 = m.complete(system="s", messages=[Message.user("hi")])
    assert r1.stop_reason == "tool_use" and r1.tool_calls[0].input == {"order_id": 1}
    assert m.complete(system="s", messages=[]).text == "done"
    with pytest.raises(ScriptExhausted):
        m.complete(system="s", messages=[])


def test_tracing_writes_jsonl():
    import agentlab.config as cfg
    with tracing.agent_span("setup-test"):
        tid = tracing.current_trace_id()
    assert (cfg.RUNS / "traces" / f"{tid}.jsonl").exists()


def test_unpriced_model_is_not_free():
    b = Budget(limit_usd=100, label="t")
    assert b.charge("some-typo-model", Usage(input_tokens=1_000_000)) >= 1.0   # fails closed
    assert b.charge("some-local-model", Usage(input_tokens=1_000_000), provider="ollama") == 0.0


def test_scripted_ids_are_deterministic_and_tool_named_name_works():
    m = ScriptedModel([call("find_customer", name="Jane")])
    r = m.complete(system="s", messages=[])
    assert r.tool_calls[0].id == "toolu_fake_1_0" and r.tool_calls[0].input == {"name": "Jane"}


def test_message_roundtrip_serialization():
    from agentlab.llm.types import Message, ThinkingBlock, ToolResultBlock, ToolUseBlock, TextBlock, ImageBlock
    m = Message("assistant", [ThinkingBlock("hm", provider="anthropic", provider_data={"signature": "x"}),
                              ToolUseBlock("t1", "lookup_order", {"order_id": 1})])
    r = Message("user", [ToolResultBlock("t1", [TextBlock("ok"), ImageBlock("image/png", "AAA")])])
    assert Message.from_dict(m.to_dict()) == m and Message.from_dict(r.to_dict()) == r
