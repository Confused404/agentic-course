"""AGENT-OFF: first_divergence (YOU_DO task 2)."""
import copy

from agentlab.context.tokens import estimate_tokens
from agentlab.perf.prefix import first_divergence

T1 = {"name": "lookup_order", "description": "Look up an order", "input_schema": {"type": "object"}}
T2 = {"name": "issue_refund", "description": "Refund an order", "input_schema": {"type": "object"}}
U1 = {"role": "user", "content": [{"type": "text", "text": "Where is 4822?"}]}
A1 = {"role": "assistant", "content": [{"type": "text", "text": "Checking."}]}
U2 = {"role": "user", "content": [{"type": "text", "text": "Thanks"}]}


def req(tools=(T1, T2), system="You are Shopfront support.", messages=(U1,)):
    return {"tools": list(tools), "system": system, "messages": list(messages), "max_tokens": 100, "opts": {}}


def test_growing_conversation_extends():
    a, b = req(messages=[U1]), req(messages=[U1, A1, U2])
    before = copy.deepcopy((a, b))
    d = first_divergence(a, b)
    assert d.section is None and d.index is None and "extends" in d.detail
    assert d.shared_tokens == estimate_tokens(T1) + estimate_tokens(T2) + estimate_tokens(a["system"]) + \
        estimate_tokens(U1)
    assert (a, b) == before


def test_tool_order_breaks_everything():
    d = first_divergence(req(), req(tools=[T2, T1]))
    assert (d.section, d.index, d.shared_tokens) == ("tools", 0, 0) and "tools" in d.detail
    d = first_divergence(req(), req(tools=[T1]))
    assert (d.section, d.index, d.shared_tokens) == ("tools", 1, estimate_tokens(T1))


def test_key_order_inside_a_tool_doesnt_matter():
    flipped = {"input_schema": T1["input_schema"], "name": T1["name"], "description": T1["description"]}
    assert first_divergence(req(), req(tools=[flipped, T2])).section is None


def test_system_offset():
    a = req(system="You are Shopfront support. Today is 2026-11-03.")
    b = req(system="You are Shopfront support. Today is 2026-11-04.")
    d = first_divergence(a, b)
    assert d.section == "system" and d.index == len("You are Shopfront support. Today is 2026-11-0")
    assert d.shared_tokens == estimate_tokens(T1) + estimate_tokens(T2) + \
        estimate_tokens("You are Shopfront support. Today is 2026-11-0")
    d = first_divergence(req(system="abc"), req(system="abcdef"))
    assert (d.section, d.index) == ("system", 3), "a prefix: the shorter length"


def test_system_blocks_compare_as_text():
    blocks = [{"text": "You are Shopfront", "cache": False}, {"text": "support.", "cache": True}]
    same = [{"text": "You are Shopfront", "cache": False}, {"text": "support.", "cache": False}]
    assert first_divergence(req(system=blocks), req(system=same)).section is None, "markers aren't content"
    assert first_divergence(req(system="You are Shopfront\n\nsupport."), req(system=blocks)).section is None


def test_edited_history():
    a = req(messages=[U1, A1, U2])
    b = req(messages=[{"role": "user", "content": [{"type": "text", "text": "[summary] ..."}]}, U2])
    d = first_divergence(a, b)
    assert (d.section, d.index) == ("messages", 0) and "messages" in d.detail
    d = first_divergence(req(messages=[U1, A1]), req(messages=[U1]))
    assert (d.section, d.index) == ("messages", 1), "curr dropped a message"


def test_messages_divergence_counts_the_shared_part_and_never_mutates():
    a, b = req(messages=[U1, A1, U2]), req(messages=[U1, {"role": "assistant", "content": []}, U2])
    before = copy.deepcopy((a, b))
    d = first_divergence(a, b)
    assert (d.section, d.index) == ("messages", 1)
    assert d.shared_tokens == estimate_tokens(T1) + estimate_tokens(T2) + estimate_tokens(a["system"]) + \
        estimate_tokens(U1)
    assert (a, b) == before
    d = first_divergence(req(system="abc"), req(system="abd"))
    assert "system" in d.detail
