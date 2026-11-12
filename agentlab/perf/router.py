"""A cascade: answer with a cheap model, escalate a step to a strong one when it matters (Node 15 TEXTBOOK §3).

CascadeModel is a ChatModel. For each call it asks the cheap model first, then decides whether to keep that answer
or re-ask the strong model the SAME request:
  - the cheap answer wants a high-stakes tool (refunds, cancellations): the action is where mistakes cost money;
  - the cheap answer has a tool call whose arguments didn't parse;
  - the conversation is struggling: one of the last tool results was an error;
  - the cheap answer is empty (end_turn with no text and no tool calls).
Signals that depend only on the INPUT (a recent tool error) are checked BEFORE calling the cheap model: no point
paying for an answer you'll throw away. The discarded cheap call (output signals) is still paid for: it's charged to the budget here (the loop only charges the answer it
receives), and counted in .wasted_usd. Escalation can be "sticky": once escalated, stay on the strong model for the
rest of the conversation (fewer cache misses from switching, fewer cheap calls thrown away).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentlab.costs import Budget
from agentlab.llm.types import ToolResultBlock

HIGH_STAKES = frozenset({"issue_refund", "cancel_order"})


@dataclass
class CascadeModel:
    cheap: Any
    strong: Any
    budget: Budget | None = None
    high_stakes: frozenset = HIGH_STAKES
    error_lookback: int = 2          # tool results to look back over for errors
    sticky: bool = True
    calls: int = 0
    escalations: int = 0
    wasted_usd: float = 0.0
    reasons: list[str] = field(default_factory=list)
    _stuck: bool = False

    def __post_init__(self) -> None:
        self.provider, self.model = self.cheap.provider, self.cheap.model

    def _use(self, m: Any) -> None:
        self.provider, self.model = m.provider, m.model      # the loop prices the answer with these

    def pre_reason(self, messages) -> str | None:
        """Input-only signal: one of the last error_lookback tool results OF THE CURRENT CUSTOMER TURN was an error
        (results after the last user message that has text)."""
        recent: list = []
        for m in reversed(messages):
            if m.role != "user":
                continue
            if any(not isinstance(b, ToolResultBlock) for b in m.content):
                break                                   # the customer's message: the turn starts here
            recent = [b for b in m.content if isinstance(b, ToolResultBlock)] + recent
        if any(b.is_error for b in recent[-self.error_lookback:]):
            return "recent tool error"
        return None

    def reason(self, resp, messages=None) -> str | None:
        """Output signals, checked on the cheap answer."""
        names = {c.name for c in resp.tool_calls}
        if names & self.high_stakes:
            return "high-stakes tool: " + ",".join(sorted(names & self.high_stakes))
        if any(c.parse_error for c in resp.tool_calls):
            return "unparseable tool arguments"
        if resp.stop_reason == "end_turn" and not resp.text.strip() and not resp.tool_calls:
            return "empty answer"
        return None

    def _escalate(self, why: str) -> None:
        self.escalations += 1
        self.reasons.append(why)
        self._stuck = self.sticky
        self._use(self.strong)

    def complete(self, *, messages, **kw):
        self.calls += 1
        if self._stuck:
            self._use(self.strong)
            return self.strong.complete(messages=messages, **kw)
        pre = self.pre_reason(messages)
        if pre is not None:
            self._escalate(pre)                     # straight to the strong model: no cheap call to throw away
            return self.strong.complete(messages=messages, **kw)
        if self.budget is not None:
            self.budget.check()
        resp = self.cheap.complete(messages=messages, **kw)
        why = self.reason(resp, messages)
        if why is None:
            self._use(self.cheap)
            return resp
        # why charge here: this answer is thrown away, but the provider bills it; without this the cascade would
        # look cheaper than it is
        if self.budget is not None:
            self.wasted_usd += self.budget.charge(self.cheap.model, resp.usage, provider=self.cheap.provider)
        self._escalate(why)
        return self.strong.complete(messages=messages, **kw)
