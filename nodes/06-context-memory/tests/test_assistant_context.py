from agentlab.assistant.support import SupportAssistant
from agentlab.context.strategies import SlidingWindow
from agentlab.llm import fake
from agentlab.llm.types import ToolUseBlock
from agentlab.memory.store import MemoryStore


def test_defaults_unchanged(conn):
    m = fake.ScriptedModel([fake.say("hi")])
    a = SupportAssistant(m, conn, 9003)
    a.chat("hello")
    assert "forget_memory" not in a.tools.names() and "update_case_notes" not in a.tools.names()
    assert a.messages == a.transcript and a.end_session() == []
    assert a.turn_stats[0]["action"] == "none" and a.turn_stats[0]["input_tokens"] >= 0


def test_transcript_keeps_everything_while_window_trims(conn):
    m = fake.ScriptedModel([fake.say(f"a{i}") for i in range(5)])
    a = SupportAssistant(m, conn, 9003, context=SlidingWindow(keep_turns=2))
    for i in range(5):
        a.chat(f"q{i}")
    assert len(a.transcript) == 10 and len(a.messages) == 4
    sent = m.calls[-1]["messages"]
    assert [x.text for x in sent] == ["q3", "a3", "q4"], "the model saw only the window"
    assert [s["action"] for s in a.turn_stats][-1] == "dropped"


def test_notes_tool_and_injection(conn):
    m = fake.ScriptedModel([fake.call("update_case_notes", notes="- rule: CONFIRM before refunds"),
                            fake.say("noted"), fake.say("ok")])
    a = SupportAssistant(m, conn, 9003, notes=True, context=SlidingWindow(keep_turns=1))
    a.chat("Rule: no refunds without CONFIRM")
    a.chat("next question")
    first = m.calls[-1]["messages"][0]
    assert "<case_notes>" in first.content[0].text and "CONFIRM before refunds" in first.content[0].text
    assert first.content[-1].text == "next question"
    assert not any("<case_notes>" in x.text for x in a.messages + a.transcript), "injected per call, not stored"
    big = SupportAssistant(fake.ScriptedModel([]), conn, 9003, notes=True)
    r = big.tools.execute(ToolUseBlock("t", "update_case_notes", {"notes": "x" * 5000}))
    assert r.is_error


def test_memory_read_path(conn):
    MemoryStore(conn).add(9003, "preference", "Prefers to be called Pree.", "call me Pree")
    MemoryStore(conn).add(9002, "preference", "Prefers to be called Marc.", "call me Marc")
    m = fake.ScriptedModel([fake.say("Hi Pree")])
    a = SupportAssistant(m, conn, 9003, memory="read")
    a.chat("hi")
    system = m.calls[0]["system"]
    assert system.rstrip().endswith("</customer_memory>"), "per-customer content goes last (cache)"
    assert "Pree" in system and "Marc" not in system
    assert "forget_memory" in a.tools.names()
    assert a.end_session() == [], "read mode never writes"


def test_memory_write_path(conn, extractor):
    ex = extractor()
    a = SupportAssistant(fake.ScriptedModel([fake.say("Sure, Pree.")]), conn, 9003, memory="on", memory_model=ex)
    a.chat("Hi, please call me Pree.")
    log = a.end_session()
    assert [(w.decision.action, w.candidate.text) for w in log] == [("store", "Prefers to be called Pree.")]
    assert "json_schema" in ex.calls[0]
    assert [x.text for x in MemoryStore(conn).active(9003)] == ["Prefers to be called Pree."]


def test_bad_memory_mode(conn):
    import pytest
    with pytest.raises(ValueError):
        SupportAssistant(fake.ScriptedModel([]), conn, 9003, memory="yes")
