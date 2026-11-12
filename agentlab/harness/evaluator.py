"""A separate, skeptical evaluator (TEXTBOOK §4): it didn't write the code, it reads the spec and the diff, it can
run the tests, and it must return a structured verdict. No verdict = fail (fail closed)."""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from agentlab.agent.loop import LoopConfig, run_agent
from agentlab.costs import Budget
from agentlab.harness import project
from agentlab.llm.types import ChatModel, Message
from agentlab.shopdev.agent import make_dev_tools
from agentlab.shopdev.sandbox import LocalSandbox
from agentlab.tools.base import Tool, ToolRegistry
from agentlab.tools.errors import ToolError

EVALUATOR_SYSTEM = """You are a skeptical QA engineer reviewing ONE feature of the `promo` project. Someone else
wrote the code and claims it's done. Your job is to find what's wrong, not to be encouraging.
Check every rule in the spec against the code and the tests: boundaries, rounding, ordering, error cases,
interactions with earlier features. Read the code; run the tests (run_tests); look for rules nobody tested, tests
weakened or special-cased, and behaviour the spec doesn't allow. Then call verdict exactly once: passed=true only if
you would ship it; otherwise passed=false with concrete, actionable issues (rule, what's wrong, where)."""


def feature_spec(ws: Path, feature_id: str) -> str:
    text = (Path(ws) / "BACKLOG.md").read_text()
    m = re.search(rf"^## {re.escape(feature_id)}:.*?(?=^## |\Z)", text, re.S | re.M)
    if not m:
        raise KeyError(f"no section for {feature_id} in BACKLOG.md")
    return m.group(0).strip()


@dataclass
class Verdict:
    passed: bool
    issues: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    turns: int = 0
    out_of_budget: bool = False      # no verdict BECAUSE the money ran out: not a judgment on the code


def evaluate(model: ChatModel, ws: Path, feature_id: str, diff: str, *, budget: Budget | None = None,
             max_turns: int = 15) -> Verdict:
    ws = Path(ws)
    out: dict = {}
    dev = make_dev_tools(ws, LocalSandbox(ws, venv=Path(sys.prefix)))

    def run_tests():
        ok, text = project.run_visible_tests(ws)
        return f"{'PASSED' if ok else 'FAILED'}\n{text[-3000:]}"

    def verdict(passed: bool, issues: list[str] | None = None):
        if out:
            raise ToolError("You already gave a verdict.")
        out.update(passed=passed, issues=[str(i) for i in (issues or [])])
        return {"recorded": True}
    # why read-only: an evaluator that can edit will "fix" things and approve its own fix
    reg = ToolRegistry([dev.get("read_file"), dev.get("list_dir"), dev.get("grep"),
                        Tool("run_tests", "Run the project's test suite (python -m pytest -q). Returns PASSED/FAILED "
                             "and the output tail.", {"type": "object", "properties": {}}, run_tests),
                        Tool("verdict", "Give your verdict once. passed: would you ship it? issues: concrete problems.",
                             {"type": "object", "properties": {"passed": {"type": "boolean"},
                                                               "issues": {"type": "array", "items": {"type": "string"}}},
                              "required": ["passed"], "additionalProperties": False}, verdict, side_effects=True)])
    task = f"{feature_spec(ws, feature_id)}\n\nThe change under review (git diff):\n```diff\n{diff[-12000:]}\n```"
    r = run_agent(model, EVALUATOR_SYSTEM, [Message.user(task)], reg,
                  LoopConfig(max_turns=max_turns, max_tokens=4000, budget=budget, agent_name="evaluator"))
    if not out:
        return Verdict(False, [f"evaluator gave no verdict (stop={r.stop})"], r.cost_usd, r.turns,
                       out_of_budget=r.stop == "budget")
    return Verdict(bool(out["passed"]) and out["passed"] is True, out["issues"], r.cost_usd, r.turns)
