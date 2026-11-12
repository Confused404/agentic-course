"""One working session of the coding agent on a promo workspace: shopdev's tools behind a project-specific gate,
optional hooks and skills, and an optional stop hook (TEXTBOOK §2-§6)."""
from __future__ import annotations

import fnmatch
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from agentlab.agent.loop import LoopConfig, LoopResult, run_agent
from agentlab.costs import Budget
from agentlab.harness import project
from agentlab.harness.hooks import HookedExecutor, protect_in_shell, syntax_check
from agentlab.llm.types import ChatModel, Message
from agentlab.shopdev.agent import make_dev_tools
from agentlab.shopdev.gated import GatedExecutor
from agentlab.shopdev.permissions import FILE_WRITE_TOOLS, Decision, PermissionGate
from agentlab.shopdev.sandbox import LocalSandbox
from agentlab.tools.base import Tool, ToolRegistry
from agentlab.tools.errors import ToolError

HARNESS_SYSTEM = """You are a careful software engineer implementing features in the `promo` project (a small
Python package). Read AGENTS.md and the feature's spec in BACKLOG.md before coding. Work in small steps: read the
code, implement, add tests for every rule in the spec, run `python -m pytest -q`, fix, repeat. Finish with a short
report: what you implemented, the tests you added, and the test results you saw. If a tool call is denied, don't
work around it: change approach or explain why you're blocked."""

PROTECTED = ["features.json", "BACKLOG.md", "AGENTS.md", "conftest.py", "skills/*"]


class ProjectGate(PermissionGate):
    """Node 03's gate, adapted for FEATURE work: new test files are allowed (writing tests is the job), existing
    tests and the harness's files are not, and running the project's own CLI is allowed."""

    def __init__(self, workspace: Path, initial_tests: set[str], progress_writable: bool = False) -> None:
        super().__init__(workspace)
        self.initial_tests = initial_tests
        self.progress_writable = progress_writable

    def decide(self, tool: str, args: dict) -> Decision:
        if tool in FILE_WRITE_TOOLS:
            rel = self._rel(str(args.get("path", "")))
            if rel is not None:
                low = rel.casefold()        # why: case-insensitive file systems (macOS) open BACKLOG.md as backlog.md
                if low == "features.json" and self.progress_writable:
                    return Decision("allow", "progress file (the harness validates your edit)")
                if any(fnmatch.fnmatch(low, g.casefold()) for g in PROTECTED):
                    return Decision("deny", f"{rel} belongs to the harness")
                if fnmatch.fnmatch(low, "tests/test_*.py"):
                    if low in {t.casefold() for t in self.initial_tests}:
                        return Decision("deny", f"{rel} is an existing test: change the code, not the test")
                    return Decision("allow", "a test file written in this run")
        d = super().decide(tool, args)
        if tool == "run_shell" and d.action == "ask":
            cmd = str(args.get("command", "")).strip()
            if re.fullmatch(r"(python3?|\.venv/bin/python) -m (promo|py_compile)( [\w./-]+)*", cmd):
                return Decision("allow", "running the project's own module")
        return d


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str


def load_skills(root: Path) -> list[Skill]:
    """skills/<name>/SKILL.md with front matter (name, description). why only the index goes in the prompt: the
    body costs tokens only when the agent decides it needs it (progressive disclosure)."""
    out = []
    for p in sorted(Path(root).glob("*/SKILL.md")):
        text = p.read_text()
        m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
        meta = dict(re.findall(r"^(\w+):\s*(.*)$", m.group(1), re.M)) if m else {}
        out.append(Skill(meta.get("name", p.parent.name), meta.get("description", ""), m.group(2) if m else text))
    return out


def skills_index(skills: list[Skill]) -> str:
    return "\n".join(f"- {s.name}: {s.description}" for s in skills)


def skill_tool(skills: list[Skill], events: list[str] | None = None) -> Tool:
    by = {s.name: s for s in skills}

    def load_skill(name: str):
        if name not in by:
            raise ToolError(f"No skill {name!r}. Available: {', '.join(by)}.")
        if events is not None:
            events.append(f"skill loaded: {name}")      # why: "did it use the skill?" must be measurable
        return by[name].body
    return Tool("load_skill", "Load a skill's full instructions by name (see the skills listed in your system prompt).",
                {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"],
                 "additionalProperties": False}, load_skill)


class _Merged:
    """Two ToolExecutors as one (the gated dev tools + the harness's own tools)."""

    def __init__(self, a, b: ToolRegistry) -> None:
        self.a, self.b = a, b

    def specs(self):
        return self.a.specs() + self.b.specs()

    def execute(self, call):
        return self.b.execute(call) if self.b.get(call.name) else self.a.execute(call)


@dataclass
class SessionResult:
    loop: LoopResult
    events: list[str] = field(default_factory=list)
    continuations: int = 0           # times the stop hook sent the agent back to work
    cost_usd: float = 0.0
    turns: int = 0


def run_session(model: ChatModel, workspace: Path, task: str, *, hooks: bool = False, skills: bool = False,
                stop_hook: bool = False, progress_writable: bool = False, budget: Budget | None = None,
                max_turns: int = 30, max_continuations: int = 2,
                protected_tests: set[str] | None = None) -> SessionResult:
    """protected_tests: the tests that existed when the WHOLE run started (default: those present now). Tests
    written by earlier sessions stay editable, so a later feature can update them."""
    ws = Path(workspace)
    initial_tests = protected_tests if protected_tests is not None else {
        p.relative_to(ws).as_posix() for p in (ws / "tests").glob("test_*.py")}
    events: list[str] = []
    tools = make_dev_tools(ws, LocalSandbox(ws, venv=Path(sys.prefix)))
    gated = GatedExecutor(tools, ProjectGate(ws, initial_tests, progress_writable),
                          approver=lambda tool, args, reason: False)       # unattended: "ask" means no
    executor = gated
    hooked = None
    if hooks:
        hooked = executor = HookedExecutor(gated, pre=[protect_in_shell(sorted(initial_tests) + ["features.json"])],
                                           post=[syntax_check(ws)])
    system = HARNESS_SYSTEM + "\n\n# Project rules (AGENTS.md)\n" + (ws / "AGENTS.md").read_text()
    if skills and (found := load_skills(ws / "skills")):
        executor = _Merged(executor, ToolRegistry([skill_tool(found, events)]))
        system += "\n\n# Skills (load one with load_skill when it applies)\n" + skills_index(found)
    cfg = LoopConfig(max_turns=max_turns, max_tokens=8000, budget=budget, agent_name="harness-session")
    res = SessionResult(run_agent(model, system, [Message.user(task)], executor, cfg))
    res.cost_usd, res.turns = res.loop.cost_usd, res.loop.turns
    # why the turn budget is shared: continuations must not give a hooked session more turns than an unhooked one
    # (that would make the ablation unfair)
    while (stop_hook and res.loop.stop == "end_turn" and res.continuations < max_continuations
           and res.turns < max_turns):
        ok, out = project.run_visible_tests(ws)
        if ok:
            break
        # why a stop hook: "done" is a claim; a red test suite is a fact. Send the agent back with the evidence.
        res.continuations += 1
        res.events.append(f"stop hook: tests failing, continuation {res.continuations}")
        msgs = res.loop.messages + [Message.user("[stop hook] You said you're done, but `python -m pytest -q` fails:\n"
                                                 + out[-2500:] + "\nFix the code (not the tests), then finish.")]
        more = run_agent(model, system, msgs, executor,
                         LoopConfig(max_turns=max_turns - res.turns, max_tokens=8000, budget=budget,
                                    agent_name="harness-session"))
        res.cost_usd += more.cost_usd
        res.turns += more.turns
        res.loop = more
    res.events += [f"gate denied {e.tool}: {e.reason}" for e in gated.log if e.action == "deny" or e.approved is False]
    if hooked is not None:
        res.events += hooked.events
    res.events += events
    return res
