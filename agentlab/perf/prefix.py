"""Where did the cacheable prefix break? AGENT-OFF (reference solution): written by hand in Node 15 YOU_DO task 2.

Tests: nodes/15-cost-latency/tests/test_prefix.py. Read TEXTBOOK §2 first. Requests are recorder.request_dict()
dicts. Use agentlab.context.tokens.estimate_tokens for token estimates.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from agentlab.context.tokens import estimate_tokens  # noqa: F401 - you will need it


@dataclass
class Divergence:
    section: str | None     # "tools" | "system" | "messages" | None (curr extends prev: the whole prev is reusable)
    index: int | None       # tools/messages: index of the first differing item; system: character offset
    detail: str             # one human-readable line, e.g. "messages[3] differs (role user)"
    shared_tokens: int      # estimated tokens of the identical prefix (what a cache could have served)


def first_divergence(prev: dict, curr: dict) -> Divergence:
    """Compare two consecutive requests of one conversation the way a prompt cache does: as one prefix, in the
    order tools -> system -> messages. Contract (each line is tested):

    1. Tools are compared item by item, in order, as canonical JSON (json.dumps(..., sort_keys=True)). The first
       index where they differ (including one list being longer) -> section "tools", index = that index.
       shared_tokens = estimate_tokens of the identical tools before it.
    2. If all tools match: the system prompts are compared as TEXT (a list of blocks is joined with "\\n\\n";
       cache markers don't count as content). First differing character offset -> section "system", index = that
       offset (if one is a prefix of the other, the shorter one's length). shared_tokens = tokens of all tools +
       estimate_tokens(the identical leading text).
    3. If tools and system match: messages are compared item by item as canonical JSON. If every message of
       `prev` equals the message at the same index of `curr` -> section None, index None (`curr` extends `prev`:
       the ideal case). Else section "messages", index = the first differing index. shared_tokens = tools +
       system + estimate_tokens of each identical leading message (estimate_tokens(message dict)).
    4. `detail` names the section and index ("tools[2] differs", "system differs at char 17: ...", ...); its exact
       wording isn't tested, but it must contain the section name, or "extends" when section is None.
    5. Never mutate the inputs.
    """
    def canon(x) -> str:
        return json.dumps(x, sort_keys=True, ensure_ascii=False)

    def text(system) -> str:
        if isinstance(system, str):
            return system
        return "\n\n".join(b["text"] if isinstance(b, dict) else str(b) for b in (system or []))

    pt, ct = prev.get("tools") or [], curr.get("tools") or []
    shared = 0
    for i in range(max(len(pt), len(ct))):
        if i >= len(pt) or i >= len(ct) or canon(pt[i]) != canon(ct[i]):
            name = (ct[i] if i < len(ct) else pt[i]).get("name", "?")
            return Divergence("tools", i, f"tools[{i}] differs ({name}): tool definitions come first, so every "
                                          f"later token is a cache miss", shared)
        shared += estimate_tokens(pt[i])
    ps, cs = text(prev.get("system")), text(curr.get("system"))
    if ps != cs:
        k = next((j for j, (a, b) in enumerate(zip(ps, cs)) if a != b), min(len(ps), len(cs)))
        return Divergence("system", k, f"system differs at char {k}: ...{cs[max(0, k - 20):k + 20]!r}...",
                          shared + estimate_tokens(ps[:k]))
    shared += estimate_tokens(ps)
    pm, cm = prev.get("messages") or [], curr.get("messages") or []
    for i, m in enumerate(pm):
        if i >= len(cm) or canon(m) != canon(cm[i]):
            role = (cm[i] if i < len(cm) else m).get("role", "?")
            return Divergence("messages", i, f"messages[{i}] differs (role {role}): an earlier turn was edited "
                                             f"(compaction? a timestamp?)", shared)
        shared += estimate_tokens(m)
    return Divergence(None, None, "curr extends prev: the whole previous request is a reusable prefix", shared)
