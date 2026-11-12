"""LLM-as-judge: one narrow rubric, evidence included, reasoning before verdict, 'unknown' allowed (TEXTBOOK §3)."""
from __future__ import annotations

import json

from agentlab.costs import Budget, BudgetExceeded
from agentlab.evals.graders import GradeResult, TrialContext
from agentlab.llm.types import ChatModel, Message, TextBlock, ToolResultBlock, ToolUseBlock

JUDGE_SYSTEM = """You grade ONE property of a customer-support transcript against ONE rubric.
The tool calls and tool results in the transcript are ground truth about what actually happened.
Judge only what the rubric asks, not style or anything else.
Answer "unknown" if the evidence is insufficient or the rubric does not apply to this transcript.
Write your reasoning first (2-4 sentences, citing the transcript), then the verdict."""

JUDGE_SCHEMA = {"type": "object", "additionalProperties": False,
                "properties": {"reasoning": {"type": "string"},
                               "verdict": {"type": "string", "enum": ["pass", "fail", "unknown"]}},
                "required": ["reasoning", "verdict"]}


def render_evidence(ctx: TrialContext, max_chars: int = 12_000) -> str:
    lines: list[str] = []
    for m in ctx.messages:
        for b in m.content:
            if isinstance(b, TextBlock) and b.text.strip():
                lines.append(f"{'CUSTOMER' if m.role == 'user' else 'ASSISTANT'}: {b.text.strip()}")
            elif isinstance(b, ToolUseBlock):
                lines.append(f"TOOL CALL {b.name}({json.dumps(b.input)})")
            elif isinstance(b, ToolResultBlock):
                text = b.text
                lines.append(f"TOOL RESULT{' (error)' if b.is_error else ''}: {text[:600]}"
                             + (" [...]" if len(text) > 600 else ""))
    out = "\n".join(lines)
    if len(out) > max_chars:
        head, tail = int(max_chars * 0.3), int(max_chars * 0.7)
        out = out[:head] + "\n[... omitted ...]\n" + out[-tail:]
    return out


def judge(model: ChatModel, rubric: str, ctx: TrialContext, budget: Budget | None = None) -> GradeResult:
    prompt = f"RUBRIC: {rubric}\n\nTRANSCRIPT:\n{render_evidence(ctx)}"
    try:
        resp = model.complete(system=JUDGE_SYSTEM, messages=[Message.user(prompt)], max_tokens=1500,
                              json_schema=JUDGE_SCHEMA, effort="low")
        if budget is not None:
            budget.charge(model.model, resp.usage, provider=model.provider)
        data = json.loads(resp.text)
        verdict = data.get("verdict")
        if verdict not in ("pass", "fail", "unknown"):
            return GradeResult("judge", "unknown", f"bad verdict {verdict!r}")
        return GradeResult("judge", verdict, str(data.get("reasoning", ""))[:500])
    except BudgetExceeded:
        raise                      # the run's cap applies to judging too; never hide it as 'unknown'
    except Exception as e:  # noqa: BLE001 - a broken judge yields 'unknown', never a fake pass
        return GradeResult("judge", "unknown", f"judge failed: {type(e).__name__}: {str(e)[:200]}")
