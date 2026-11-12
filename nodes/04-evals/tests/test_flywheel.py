"""Traces -> candidate eval tasks."""
import yaml

from agentlab.assistant.support import SupportAssistant
from agentlab.evals.flywheel import candidates_to_yaml, mine_traces
from agentlab.llm.fake import ScriptedModel, call, say


def test_mine_flags_and_yaml(conn):
    import agentlab.config as cfg
    m = ScriptedModel([call("lookup_order", order_id=99999), say("Hmm, not found."),
                       say("Hello!"),
                       call("escalate_to_human", summary="Customer says package lost.", order_id=4824), say("Escalated.")])
    a = SupportAssistant(m, conn, 9001)
    a.chat("where is order 99999?")        # tool error
    a.chat("hi")                          # clean: not flagged
    a.chat("my package is lost")          # escalation
    cands = mine_traces(cfg.RUNS / "traces")
    by_msg = {c["user_message"]: c for c in cands}
    assert set(by_msg) == {"where is order 99999?", "my package is lost"}
    assert "tool_error" in by_msg["where is order 99999?"]["reasons"]
    assert "escalated" in by_msg["my package is lost"]["reasons"] and by_msg["my package is lost"]["customer_id"] == 9001
    assert by_msg["my package is lost"]["turns"] == ["where is order 99999?", "hi", "my package is lost"], \
        "a flagged turn keeps the conversation that led to it"
    stubs = yaml.safe_load(candidates_to_yaml(cands))
    assert len(stubs) == 2 and all(s["id"].startswith("cand_") and s["graders"] == [] for s in stubs)
    assert stubs[0]["turns"] and "reasons" in stubs[0]["note"]
