"""Durable agent runs (TEXTBOOK §3-§5): every step journaled before the next, so a run can be resumed after a crash,
paused for a human approval (the process may exit meanwhile), and replayed as a timeline.

Side effects get at-most-once-or-reconciled semantics: the INTENT is journaled before a side-effecting tool runs
and the RESULT after; on resume, an intent without a result is "reconciled" (look before you redo) instead of run
again blindly.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from agentlab import tracing
from agentlab.costs import Budget
from agentlab.llm.types import ChatModel, Message, ToolResultBlock, ToolUseBlock, to_dict
from agentlab.reliability import recovery as recovery_module
from agentlab.reliability import retry as retry_module
from agentlab.reliability.journal import Journal
from agentlab.reliability.recovery import PendingCall, RecoveryPlan
from agentlab.tools.base import ToolRegistry

Reconciler = Callable[[dict], dict | None]      # args -> the result if it already happened, else None
STOPS = {"end_turn": "end_turn", "stop_sequence": "end_turn", "max_tokens": "max_tokens", "refusal": "refusal",
         "context_window_exceeded": "context_window_exceeded"}     # same mapping as Node 02's run_agent
Hook = Callable[[str, dict], None]              # (point, info): crash injection and observation


@dataclass
class DurableResult:
    run_id: str
    status: str                 # done | awaiting_approval | needs_human
    stop: str = ""
    final_text: str = ""
    turns: int = 0
    cost_usd: float = 0.0
    note: str = ""


class DurableAgent:
    def __init__(self, journal: Journal, tools: ToolRegistry, *, side_effect_tools: set[str] | None = None,
                 approval_tools: set[str] = frozenset(), reconcilers: dict[str, Reconciler] | None = None,
                 hook: Hook | None = None) -> None:
        self.journal, self.tools = journal, tools
        self.side_effect_tools = side_effect_tools if side_effect_tools is not None else {
            n for n in tools.names() if tools.get(n).side_effects}
        self.approval_tools = set(approval_tools)
        self.reconcilers = reconcilers or {}
        self.hook = hook or (lambda point, info: None)

    # ------------------------------------------------------------ journal helpers
    def _append(self, run_id: str, kind: str, **data) -> dict:
        e = self.journal.append(run_id, kind, **data)
        self.hook("journaled", e)                # why after: a crash here means "it's durable, the next step isn't"
        return e

    def _result(self, run_id: str, call_id: str, res: ToolResultBlock, **extra) -> ToolResultBlock:
        self._append(run_id, "result", call_id=call_id, content=res.text, is_error=res.is_error, **extra)
        return ToolResultBlock(call_id, res.text, res.is_error)

    # ------------------------------------------------------------ public API
    def start(self, run_id: str, model: ChatModel, system: str, messages: list[Message], *,
              budget: Budget | None = None, max_turns: int = 10, max_tokens: int = 2048) -> DurableResult:
        if self.journal.entries(run_id):
            raise ValueError(f"run {run_id!r} already exists: resume it instead")
        self._append(run_id, "start", system=system, messages=[to_dict(m) for m in messages],
                     config={"max_turns": max_turns, "max_tokens": max_tokens})
        return self.resume(run_id, model, budget=budget)

    def approve(self, run_id: str, call_id: str, approved: bool, by: str, note: str = "") -> None:
        es = self.journal.entries(run_id)
        asked = {e["call_id"] for e in es if e["kind"] == "approval_requested"}
        decided = {e["call_id"] for e in es if e["kind"] == "approval"}
        if call_id not in asked:
            raise KeyError(f"no approval was requested for {call_id} in run {run_id}")
        if call_id in decided:
            raise ValueError(f"{call_id} was already decided")
        self._append(run_id, "approval", call_id=call_id, approved=approved, by=by, note=note)

    def pending_approvals(self, run_id: str) -> list[dict]:
        es = self.journal.entries(run_id)
        decided = {e["call_id"] for e in es if e["kind"] == "approval"}
        return [e for e in es if e["kind"] == "approval_requested" and e["call_id"] not in decided]

    def resolve_manually(self, run_id: str, call_id: str, content: str, by: str) -> None:
        """A person checked what happened to a call the runner couldn't reconcile (`needs_human`) and records the
        outcome as its result; the next resume continues from there."""
        plan = recovery_module.plan_recovery(self.journal.entries(run_id), self.side_effect_tools)
        if call_id not in {p.call_id for p in plan.pending}:
            raise KeyError(f"{call_id} is not an unresolved call of run {run_id}")
        self._append(run_id, "result", call_id=call_id, content=content, is_error=False, reconciled=True,
                     resolved_by=by)

    def resume(self, run_id: str, model: ChatModel, *, budget: Budget | None = None) -> DurableResult:
        es = self.journal.entries(run_id)
        plan = recovery_module.plan_recovery(es, self.side_effect_tools)
        turns = sum(e["kind"] == "assistant" for e in es)
        if plan.status == "done":
            end = next((e for e in reversed(es) if e["kind"] == "end"), None)
            if end is None:
                # crashed after the final answer was journaled, before "end": finish without asking the model again
                last = next(e for e in reversed(es) if e["kind"] == "assistant")
                stop = STOPS.get(last.get("stop_reason") or "end_turn", "other")
                final = Message.from_dict(last["message"]).text
                end = self._append(run_id, "end", stop=stop, final_text=final)
            return DurableResult(run_id, "done", end["stop"], end.get("final_text", ""), turns)
        if plan.status == "awaiting_approval":
            return DurableResult(run_id, "awaiting_approval", "awaiting_approval", turns=turns,
                                 note=", ".join(p.call_id for p in plan.pending if p.action == "await_approval"))
        return self._drive(run_id, model, plan, turns, budget)

    # ------------------------------------------------------------ the loop
    def _resolve(self, run_id: str, p: PendingCall, block: ToolUseBlock | None = None) -> ToolResultBlock | str:
        """Run or reconcile one pending call. Returns its result, or a status string to stop with."""
        if block is not None and block.parse_error:
            # same as Node 02: arguments that didn't parse are never executed (they'd run as {}); tell the model
            return self._result(run_id, p.call_id, ToolResultBlock(
                p.call_id, f"Invalid tool arguments ({block.parse_error}). Call the tool again with valid JSON.",
                is_error=True))
        if p.action == "reconcile":
            rec = self.reconcilers.get(p.tool)
            if rec is None:
                # why stop: we can't tell whether it happened, and guessing either way can be wrong (double refund
                # or none). A person must look.
                return "needs_human"
            found = rec(p.args)
            if found is not None:
                return self._result(run_id, p.call_id, ToolResultBlock(p.call_id, _json(found)), reconciled=True)
        if p.tool in self.approval_tools and not self._approved(run_id, p.call_id):
            self._append(run_id, "approval_requested", call_id=p.call_id, tool=p.tool, args=p.args)
            return "awaiting_approval"
        self._append(run_id, "intent", call_id=p.call_id, tool=p.tool, args=p.args)
        with tracing.tool_span(p.tool, p.call_id, p.args) as span:
            res = self.tools.execute(ToolUseBlock(p.call_id, p.tool, p.args))
            tracing.record_tool_result(span, res.text, res.is_error)
        self.hook("executed", {"call_id": p.call_id, "tool": p.tool})
        return self._result(run_id, p.call_id, res)

    def _approved(self, run_id: str, call_id: str) -> bool:
        return any(e["kind"] == "approval" and e["call_id"] == call_id and e["approved"]
                   for e in self.journal.entries(run_id))

    def _drive(self, run_id: str, model: ChatModel, plan: RecoveryPlan, turns: int,
               budget: Budget | None) -> DurableResult:
        msgs = list(plan.messages)
        cost0 = budget.spent_usd if budget else 0.0
        max_turns = int(plan.config.get("max_turns", 10))
        max_tokens = int(plan.config.get("max_tokens", 2048))
        results = {r.tool_use_id: r for r in plan.results}
        pending = list(plan.pending)
        used_ids = {b.id for m in msgs if m.role == "assistant" for b in m.content if isinstance(b, ToolUseBlock)}
        with tracing.agent_span("durable"):
            while True:
                if pending or results:
                    open_calls = [b for b in msgs[-1].content if isinstance(b, ToolUseBlock)]
                    blocks = {b.id: b for b in open_calls}
                    for p in pending:
                        out = self._resolve(run_id, p, blocks.get(p.call_id))
                        if isinstance(out, str):
                            return DurableResult(run_id, out, out, turns=turns, note=p.call_id,
                                                 cost_usd=(budget.spent_usd - cost0) if budget else 0.0)
                        results[p.call_id] = out
                    msgs.append(Message("user", [results[c.id] for c in open_calls]))
                    pending, results = [], {}
                if turns >= max_turns:
                    stop = "max_turns"
                    break
                if budget is not None:
                    budget.check()
                with tracing.chat_span(model.provider, model.model) as span:
                    resp = model.complete(system=plan.system, messages=msgs, tools=self.tools.specs(),
                                          max_tokens=max_tokens)
                    turns += 1
                    msg = Message("assistant", list(resp.content))
                    calls = list(resp.tool_calls) if resp.stop_reason == "tool_use" else []
                    ids = [c.id for c in calls]
                    if len(set(ids)) != len(ids) or set(ids) & used_ids:
                        # why refuse: recovery matches results to calls by id; a reused id could make a result of one
                        # call look like the result of another. Real providers never reuse ids; fakes might.
                        raise ValueError(f"duplicate tool call ids in run {run_id}: {ids}")
                    used_ids.update(ids)
                    # why journal before charging: if charging raises (budget), the paid answer is still recorded and
                    # a resume continues from it instead of paying for it again
                    self._append(run_id, "assistant", message=to_dict(msg), stop_reason=resp.stop_reason)
                    cost = budget.charge(model.model, resp.usage, provider=model.provider) if budget else None
                    tracing.record_response(span, resp, cost)
                msgs.append(msg)
                if resp.stop_reason == "pause_turn" and not calls:
                    continue                    # Node 02: the provider paused a long turn; call again, no user message
                if not calls:
                    stop = STOPS.get(resp.stop_reason, "other")
                    break
                pending = [PendingCall(c.id, c.name, dict(c.input), "execute") for c in calls]
        final = msgs[-1].text if msgs and msgs[-1].role == "assistant" else ""
        self._append(run_id, "end", stop=stop, final_text=final)
        return DurableResult(run_id, "done", stop, final, turns, (budget.spent_usd - cost0) if budget else 0.0)


def _json(d: dict) -> str:
    import json
    return json.dumps(d, sort_keys=True, default=str)


def run_until_done(agent: DurableAgent, run_id: str, model: ChatModel, *, budget: Budget | None = None,
                   max_resumes: int = 10, sleep: Callable[[float], None] = time.sleep) -> tuple[DurableResult, int]:
    """Resume after crashes, like a supervisor restarting a worker. Returns (result, resumes).
    Resumes on a Crash, or on a provider error that outlived the model's retries (retryable, or the breaker is
    open), waiting with backoff first. Anything else (a bug, a bad request, out of budget) is raised at once:
    restarting doesn't fix it. After max_resumes the last error is raised with `.resumes` set on it."""
    from agentlab.reliability.faults import Crash
    from agentlab.reliability.resilient import CircuitOpen
    resumes = 0
    while True:
        try:
            return agent.resume(run_id, model, budget=budget), resumes
        except Crash as e:
            err: BaseException = e
        except Exception as e:  # noqa: BLE001 - classified right below
            if not (isinstance(e, CircuitOpen) or retry_module.is_retryable(e)):
                raise
            err = e
            sleep(retry_module.backoff_delay(resumes + 1, base=1.0, cap=30.0))
        if resumes >= max_resumes:
            err.resumes = resumes  # type: ignore[attr-defined]
            raise err
        resumes += 1


def timeline(entries: list[dict]) -> str:
    """A human-readable run history from the journal (TEXTBOOK §6)."""
    lines = []
    t0 = entries[0]["ts"] if entries else 0.0
    for e in entries:
        k = e["kind"]
        dt = f"+{e['ts'] - t0:6.2f}s"
        if k == "start":
            first = e["messages"][0]["content"][0].get("text", "") if e["messages"] else ""
            detail = f"user: {first[:80]}"
        elif k == "assistant":
            blocks = e["message"]["content"]
            texts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
            calls = [f"{b['name']}({_json(b['input'])[:60]})" for b in blocks if b.get("type") == "tool_use"]
            detail = "; ".join(filter(None, [" ".join(texts)[:80], ", ".join(calls)]))
        elif k in ("intent", "approval_requested"):
            detail = f"{e['tool']} {_json(e['args'])[:80]}"
        elif k == "result":
            detail = ("ERROR " if e["is_error"] else "") + ("[reconciled] " if e.get("reconciled") else "") + \
                     (f"[by {e['resolved_by']}] " if e.get("resolved_by") else "") + e["content"][:80]
        elif k == "approval":
            detail = f"{'APPROVED' if e['approved'] else 'DENIED'} by {e['by']}: {e.get('note', '')}"
        else:
            detail = f"stop={e['stop']}: {e.get('final_text', '')[:80]}"
        lines.append(f"{e['seq']:3} {dt} {k:18} {detail}")
    return "\n".join(lines)
