"""Context strategies: what the model sees on the next call (TEXTBOOK §3-§5).

Every strategy takes the WORKING history (not the transcript: that stays complete for graders and audits) and
returns the list to send. Rules all strategies follow:
- never mutate the input messages (the transcript shares the objects);
- never orphan a tool result (split_for_compaction guarantees the cut points);
- act in large steps, only above a trigger: every change to early messages invalidates the prompt cache from that
  point on (TEXTBOOK §5), so a strategy that edits the history on every turn pays full price on every turn.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Protocol

from agentlab.context.split import is_customer_turn, split_for_compaction
from agentlab.context.tokens import estimate_request
from agentlab.costs import Budget, BudgetExceeded
from agentlab.llm.types import ChatModel, Message, TextBlock, ThinkingBlock, ToolResultBlock, ToolSpec, ToolUseBlock

SUMMARY_TAG = "conversation_summary"
# why: results of side-effecting tools are the record of what was DONE. Clearing them invites the model to redo
# (or deny) an action. Read-only results can be fetched again.
DEFAULT_KEEP_TOOLS = ("issue_refund", "cancel_order", "escalate_to_human", "forget_memory", "update_case_notes")


def _should_act(n: int, trigger: int | None, last_after: int | None, min_growth: int | None) -> bool:
    """Act above the trigger, and then only after the context has grown by `min_growth` since the last action
    (default trigger // 4). why: if one action can't get below the trigger (a long summary, many recent turns), a
    plain threshold acts on EVERY turn: a paid call and a full cache miss each time (TEXTBOOK §5, hysteresis)."""
    if trigger is None:
        return True
    if n <= trigger:
        return False
    growth = trigger // 4 if min_growth is None else min_growth
    return last_after is None or n - last_after >= growth


def _escape_tag(text: str, tag: str) -> str:
    # why: text we wrap in a tag must not be able to close it (or open a fake one) from inside
    return text.replace(f"</{tag}>", f"</{tag}_>").replace(f"<{tag}>", f"<{tag}_>")


@dataclass
class PrepareStats:
    strategy: str
    action: str                 # "none" | "dropped" | "cleared" | "compacted" | "failed"
    before_tokens: int
    after_tokens: int
    detail: str = ""


class ContextStrategy(Protocol):
    name: str
    history: list[PrepareStats]

    def prepare(self, messages: list[Message], *, system: str, tools: list[ToolSpec]) -> list[Message]: ...


@dataclass
class Full:
    """Send everything. The baseline: correct until the window (or the bill) runs out."""
    name: str = "full"
    history: list[PrepareStats] = field(default_factory=list)

    def prepare(self, messages, *, system, tools):
        n = estimate_request(system, tools, messages)
        self.history.append(PrepareStats(self.name, "none", n, n))
        return list(messages)


@dataclass
class SlidingWindow:
    """Keep the last `keep_turns` customer turns; drop the rest. trigger_tokens=None drops on EVERY turn (the naive
    version: the start of the history changes every turn, so nothing after the tools is ever cached)."""
    keep_turns: int = 6
    trigger_tokens: int | None = None
    min_growth: int | None = None
    name: str = "window"
    history: list[PrepareStats] = field(default_factory=list)
    _last_after: int | None = None

    def prepare(self, messages, *, system, tools):
        n = estimate_request(system, tools, messages)
        if not _should_act(n, self.trigger_tokens, self._last_after, self.min_growth):
            self.history.append(PrepareStats(self.name, "none", n, n))
            return list(messages)
        old, kept = split_for_compaction(messages, self.keep_turns)
        if not old:
            self.history.append(PrepareStats(self.name, "none", n, n))
            return kept
        m = estimate_request(system, tools, kept)
        self._last_after = m
        self.history.append(PrepareStats(self.name, "dropped", n, m, f"{len(old)} messages"))
        return kept


def _stub(call: ToolUseBlock | None, original: str) -> str:
    what = f"{call.name}({json.dumps(call.input, ensure_ascii=False)})" if call else "this tool call"
    return (f"[result cleared to save context: {what} returned {len(original)} characters. "
            f"Call the tool again if you need the details.]")


@dataclass
class ClearToolResults:
    """Above the trigger, replace the content of old tool results with a short stub, keeping the most recent
    `keep_recent` results and anything from side-effecting tools. The calls stay, so the model still sees WHAT it
    looked up, and can look it up again."""
    trigger_tokens: int = 8000
    keep_recent: int = 3
    keep_tools: tuple[str, ...] = DEFAULT_KEEP_TOOLS
    min_growth: int | None = None
    name: str = "clear"
    history: list[PrepareStats] = field(default_factory=list)
    _last_after: int | None = None

    def prepare(self, messages, *, system, tools):
        n = estimate_request(system, tools, messages)
        if not _should_act(n, self.trigger_tokens, self._last_after, self.min_growth):
            self.history.append(PrepareStats(self.name, "none", n, n))
            return list(messages)
        calls = {b.id: b for m in messages for b in m.content if isinstance(b, ToolUseBlock)}
        results = [(i, j) for i, m in enumerate(messages) for j, b in enumerate(m.content)
                   if isinstance(b, ToolResultBlock)]
        clearable = [(i, j) for i, j in results[: max(0, len(results) - self.keep_recent)]
                     if (c := calls.get(messages[i].content[j].tool_use_id)) is None or c.name not in self.keep_tools]
        out = list(messages)
        cleared = 0
        for i, j in clearable:
            b = out[i].content[j]
            text = b.content if isinstance(b.content, str) else ""
            if text.startswith("[result cleared"):
                continue
            content = list(out[i].content)          # copy-on-write: never touch the transcript's objects
            content[j] = replace(b, content=_stub(calls.get(b.tool_use_id), text))
            out[i] = Message(out[i].role, content)
            cleared += 1
        m = estimate_request(system, tools, out)
        if cleared:
            self._last_after = m
        self.history.append(PrepareStats(self.name, "cleared" if cleared else "none", n, m,
                                         f"{cleared} results" + (" (still above trigger)" if m > self.trigger_tokens else "")))
        return out


def render_for_summary(messages: list[Message], max_result_chars: int = 1500) -> str:
    """The old part of the conversation as plain text for the summariser. Thinking is dropped (it is the model's
    scratch work, not facts); long tool results are truncated with a marker."""
    lines = []
    for m in messages:
        for b in m.content:
            if isinstance(b, ThinkingBlock):
                continue
            if isinstance(b, TextBlock) and b.text.strip():
                who = "CUSTOMER" if m.role == "user" else "ASSISTANT"
                lines.append(f"{who}: {b.text.strip()}")
            elif isinstance(b, ToolUseBlock):
                lines.append(f"ASSISTANT CALLED {b.name}({json.dumps(b.input, ensure_ascii=False)})")
            elif isinstance(b, ToolResultBlock):
                text = b.content if isinstance(b.content, str) else "[non-text result]"
                if len(text) > max_result_chars:
                    text = text[:max_result_chars] + f" …[{len(text) - max_result_chars} more characters]"
                lines.append(f"TOOL RESULT{' (error)' if b.is_error else ''}: {text}")
    return "\n".join(lines)


@dataclass
class Compaction:
    """Above the trigger, summarise everything before the last `keep_turns` customer turns with `summarizer`, and
    put the summary in front of the first kept turn. Earlier summaries are part of the old messages, so they are
    folded into the new one (recursive summarisation)."""
    summarizer: ChatModel
    prompt: str
    trigger_tokens: int = 8000
    keep_turns: int = 4
    budget: Budget | None = None
    max_summary_tokens: int = 1500
    max_failures: int = 3
    min_growth: int | None = None
    name: str = "compact"
    history: list[PrepareStats] = field(default_factory=list)
    failures: int = 0                  # CONSECUTIVE failures; a success resets it
    summaries: list[str] = field(default_factory=list)
    _last_after: int | None = None

    def prepare(self, messages, *, system, tools):
        n = estimate_request(system, tools, messages)
        if (not _should_act(n, self.trigger_tokens, self._last_after, self.min_growth)
                or self.failures >= self.max_failures):
            # why the failure cap: a summariser that keeps failing would add a paid call to every turn
            self.history.append(PrepareStats(self.name, "none", n, n))
            return list(messages)
        old, kept = split_for_compaction(messages, self.keep_turns)
        if not old:
            self.history.append(PrepareStats(self.name, "none", n, n, "too few turns to compact"))
            return kept
        try:
            if self.budget:
                self.budget.check()
            resp = self.summarizer.complete(system=self.prompt, messages=[Message.user(render_for_summary(old))],
                                            tools=None, max_tokens=self.max_summary_tokens)
            if self.budget:
                self.budget.charge(self.summarizer.model, resp.usage, provider=self.summarizer.provider)
            summary = resp.text.strip()
            if resp.stop_reason == "max_tokens":
                # why: a truncated summary loses its LAST sections, which in a template are actions and open items
                raise RuntimeError(f"summary truncated at max_tokens={self.max_summary_tokens}")
            if not summary or resp.stop_reason != "end_turn":
                raise RuntimeError(f"summariser returned stop={resp.stop_reason}, {len(summary)} chars")
        except BudgetExceeded:
            raise                       # the run's cap: not a summariser failure
        except Exception as e:  # noqa: BLE001
            self.failures += 1
            self.history.append(PrepareStats(self.name, "failed", n, n, f"{type(e).__name__}: {e}"))
            return list(messages)
        self.failures = 0
        self.summaries.append(summary)
        first = kept[0]
        # why the framing: this text sits inside a user message but was written by the system (a summariser that
        # also read tool results). Say so, so it isn't read as the customer speaking.
        head = TextBlock(f"<{SUMMARY_TAG}>\n[Written by the support system, not the customer: a summary of the "
                         f"earlier part of this conversation; older messages were removed to save space.]\n"
                         f"{_escape_tag(summary, SUMMARY_TAG)}\n</{SUMMARY_TAG}>\n\n")
        out = [Message(first.role, [head, *first.content]), *kept[1:]]
        m = estimate_request(system, tools, out)
        self._last_after = m
        detail = f"{len(old)} messages -> {len(summary)} chars"
        if m > self.trigger_tokens:
            detail += " (still above trigger: raise the trigger, keep fewer turns, or shorten summaries)"
        self.history.append(PrepareStats(self.name, "compacted", n, m, detail))
        return out


def make_strategy(spec: str, model: ChatModel | None = None, budget: Budget | None = None,
                  prompt: str | None = None) -> ContextStrategy:
    """'full' | 'window:K[:TRIGGER]' | 'clear:TRIGGER[:KEEP_RECENT]' | 'compact:TRIGGER[:KEEP_TURNS]'."""
    name, *args = spec.split(":")
    try:
        nums = [int(a) for a in args]
    except ValueError:
        raise ValueError(f"bad context strategy {spec!r}: numbers expected after the name") from None
    if any(x < 1 for x in nums):
        raise ValueError(f"bad context strategy {spec!r}: numbers must be >= 1")
    if name == "full" and not nums:
        return Full()
    if name == "window" and 1 <= len(nums) <= 2:
        return SlidingWindow(nums[0], nums[1] if len(nums) == 2 else None)
    if name == "clear" and 1 <= len(nums) <= 2:
        return ClearToolResults(nums[0], *(nums[1:]))
    if name == "compact" and 1 <= len(nums) <= 2:
        if prompt is None:
            from agentlab.context.prompts import COMPACTION_PROMPT as prompt
        if not prompt:
            raise ValueError("compaction needs COMPACTION_PROMPT (agentlab/context/prompts.py, YOU_DO task 5)")
        if model is None:
            raise ValueError("compaction needs a summariser model")
        return Compaction(model, prompt, nums[0], *(nums[1:]), budget=budget)
    raise ValueError(f"unknown context strategy {spec!r}: use full | window:K[:T] | clear:T[:K] | compact:T[:K]")


__all__ = ["ClearToolResults", "Compaction", "ContextStrategy", "Full", "PrepareStats", "SlidingWindow",
           "is_customer_turn", "make_strategy", "render_for_summary"]
