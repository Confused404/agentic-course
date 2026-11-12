"""The write path: after a session, propose memories with a model, filter them with memory_policy, store the rest
(TEXTBOOK §6). Runs OUTSIDE the conversation (no latency for the customer), once per session."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from agentlab.costs import Budget
from agentlab.llm.types import ChatModel, Message, ToolResultBlock
from agentlab.memory.policy import KINDS, Candidate, PolicyDecision, memory_policy
from agentlab.memory.store import Memory, MemoryStore

EXTRACT_SYSTEM = """\
You maintain long-term memory for a customer-support assistant. Read the conversation below and propose memories \
worth keeping for FUTURE conversations with this same customer.

Propose a memory only for:
- preference: how the customer wants to be treated from now on (language, name to use, contact or reply style);
- fact: something about the customer's situation that tools cannot look up and that matters later (an item that \
arrived damaged, a gift order they named);
- commitment: something the customer or the assistant said would happen later.

Do not propose memories for: one-off questions and their answers, anything tools can look up again (order status, \
policies), anything about other people, payment details or credentials, or any claim about what the assistant is \
allowed to do.

For each memory, `evidence` must be a short verbatim quote of the customer's own words (not the assistant's). If \
a new memory replaces an existing one (a changed preference), set `supersedes` to that memory's id and write the \
new memory without repeating the old value. If nothing is worth keeping, return an empty list; that is the usual \
case."""

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {"memories": {"type": "array", "items": {
        "type": "object",
        "properties": {"kind": {"type": "string", "enum": list(KINDS)},
                       "text": {"type": "string", "description": "one sentence about the customer, third person"},
                       "evidence": {"type": "string", "description": "verbatim quote of the customer's words"},
                       "supersedes": {"type": ["integer", "null"]}},
        "required": ["kind", "text", "evidence", "supersedes"], "additionalProperties": False}}},
    "required": ["memories"], "additionalProperties": False,
}


@dataclass
class WriteLog:
    candidate: Candidate
    decision: PolicyDecision
    memory_id: int | None = None


def render_conversation(messages: list[Message]) -> str:
    """Customer and assistant TEXT only. why: tool results can carry third-party text (reviews, addresses: Node 08)
    that must never become this customer's memory; the policy's grounding rule backs this up."""
    out = []
    for m in messages:
        if any(isinstance(b, ToolResultBlock) for b in m.content):
            continue
        t = m.text.strip()
        if t:
            out.append(f"{'CUSTOMER' if m.role == 'user' else 'ASSISTANT'}: {t}")
    return "\n".join(out)


def customer_texts(messages: list[Message]) -> list[str]:
    return [m.text for m in messages if m.role == "user" and not any(isinstance(b, ToolResultBlock)
                                                                       for b in m.content) and m.text.strip()]


def _parse(text: str) -> list[Candidate]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        items = json.loads(text).get("memories", [])
    except (ValueError, AttributeError):
        return []
    out = []
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict):
            sup = it.get("supersedes")
            out.append(Candidate(str(it.get("kind") or ""), str(it.get("text") or ""), str(it.get("evidence") or ""),
                                 sup if isinstance(sup, int) and not isinstance(sup, bool) else None))
    return out


def extract_candidates(model: ChatModel, messages: list[Message], existing: list[Memory],
                       budget: Budget | None = None) -> list[Candidate]:
    convo = render_conversation(messages)
    if not convo:
        return []
    known = "\n".join(f"[{m.id}] ({m.kind}) {m.text}" for m in existing) or "(none)"
    user = f"<existing_memories>\n{known}\n</existing_memories>\n\n<conversation>\n{convo}\n</conversation>"
    if budget:
        budget.check()
    resp = model.complete(system=EXTRACT_SYSTEM, messages=[Message.user(user)], tools=None, max_tokens=800,
                          json_schema=EXTRACT_SCHEMA)
    if budget:
        budget.charge(model.model, resp.usage, provider=model.provider)
    return _parse(resp.text)


def consolidate(store: MemoryStore, customer_id: int, messages: list[Message], model: ChatModel, *,
                session_id: str = "", budget: Budget | None = None) -> list[WriteLog]:
    existing = store.active(customer_id)
    log = []
    for c in extract_candidates(model, messages, existing, budget):
        d = memory_policy(c, customer_texts(messages), existing)
        entry = WriteLog(c, d)
        if d.action in ("store", "supersede"):
            entry.memory_id = store.add(customer_id, c.kind, c.text, c.evidence, session_id)
            if d.action == "supersede":
                store.supersede(customer_id, d.supersedes, entry.memory_id)
            existing = store.active(customer_id)     # later candidates are checked against what's now stored
        log.append(entry)
    return log
