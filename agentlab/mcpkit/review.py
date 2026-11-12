"""Reviewing tool metadata before you trust it. AGENT-OFF (reference solution): written by hand in Node 11 YOU_DO task 3.

Finding is GIVEN. Implement review_tool() to satisfy its docstring. Tests: nodes/11-mcp/tests/test_review.py.
Read TEXTBOOK §5 first. Standard library only (re, unicodedata).

why not reuse your Node 08 detector: that one reads DATA (reviews, tickets), where any instruction is suspicious.
Tool descriptions are instructions by design ("Use before issue_refund"), so the signal is different: instructions
about OTHER servers' tools, secrecy, hidden markup, and requests to move personal data into arguments.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from agentlab.mcpkit.pins import ToolDef

RULES = ("cross_server", "scope_creep", "secrecy", "hidden_markup", "data_request")


@dataclass(frozen=True)
class Finding:
    rule: str          # one of RULES
    detail: str        # what matched, short, for the human reviewer


def review_tool(tool: ToolDef, all_tools: list[ToolDef]) -> list[Finding]:
    """Findings for one tool's description (and its parameters' descriptions), at most one per rule, in RULES order.
    [] means nothing suspicious was found, not that the tool is safe. Contract (each line is tested):

    0. Scan the tool's description plus every input_schema property's "description" (top level only), joined with
       newlines. Match case-insensitively; before matching, apply Unicode NFKC normalisation. Phrases and names
       match as whole words; "within N characters" counts newlines as characters.
    1. cross_server: the text names a tool (whole word; '-' and '_' interchangeable) that some OTHER server in
       all_tools offers and the tool's own server does NOT. (Mentioning your own server's tools is normal guidance.)
    2. scope_creep: the text addresses tools in general: "other tools", "other connected", "any tool", "all tools",
       "before using any", "other <word> tools" (e.g. "other lookup_order tools").
    3. secrecy: the text asks to keep something from the user: "do not"/"don't"/"never" followed within 20
       characters by tell|mention|show|reveal|inform|disclose, then within 20 characters by "user" or "customer";
       or "without telling"; or "keep this secret|confidential|hidden"; or "internal implementation detail".
    4. hidden_markup: angle-bracket tags whose name is important|system|instructions|instruction|secret|hidden
       (e.g. "<IMPORTANT>", "</system>"), HTML comments ("<!--"), or any invisible/formatting character BEFORE
       normalisation: U+200B–U+200F, U+202A–U+202E, U+2060–U+2064, U+2066–U+2069, U+FEFF, U+E0000–U+E007F.
    5. data_request: pass|include|send|provide|put|add, followed within 80 characters by
       email|address|phone|password|card number|full name|identity|date of birth.
    """
    raw = "\n".join([tool.description] + [str(p.get("description", "")) for p in
                                            (tool.input_schema.get("properties") or {}).values()
                                            if isinstance(p, dict)])
    text = unicodedata.normalize("NFKC", raw).casefold()
    norm = lambda n: n.casefold().replace("-", "_")  # noqa: E731
    found: dict[str, str] = {}

    own = {norm(t.name) for t in all_tools if t.server == tool.server} | {norm(tool.name)}
    foreign = sorted({norm(t.name) for t in all_tools if t.server != tool.server} - own)
    flat = text.replace("-", "_")
    for name in foreign:
        if re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", flat):
            found["cross_server"] = f"names {name}, a tool of another server"
            break
    m = re.search(r"\b(other tools|other connected|any tool|all tools|before using any|other [\w-]+ tools)\b", text)
    if m:
        found["scope_creep"] = m.group(0)
    m = re.search(r"\b(do not|don't|never)\b.{0,20}\b(tell|mention|show|reveal|inform|disclose)\b.{0,20}\b(user|customer)"
                  r"|without telling|keep this (secret|confidential|hidden)|internal implementation detail", text, re.S)
    if m:
        found["secrecy"] = m.group(0)
    invisible = [c for c in raw if 0x200B <= ord(c) <= 0x200F or 0x202A <= ord(c) <= 0x202E
                 or 0x2060 <= ord(c) <= 0x2064 or 0x2066 <= ord(c) <= 0x2069 or ord(c) == 0xFEFF
                 or 0xE0000 <= ord(c) <= 0xE007F]
    m = re.search(r"</?\s*(important|system|instructions|instruction|secret|hidden)\s*>|<!--", text)
    if invisible:
        found["hidden_markup"] = f"{len(invisible)} invisible character(s), first U+{ord(invisible[0]):04X}"
    elif m:
        found["hidden_markup"] = m.group(0)
    m = re.search(r"\b(pass|include|send|provide|put|add)\b.{0,80}?\b(email|address|phone|password|card number|"
                  r"full name|identity|date of birth)", text, re.S)
    if m:
        found["data_request"] = m.group(0)[:80]
    return [Finding(r, found[r]) for r in RULES if r in found]
