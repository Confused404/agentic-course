"""shopdev: the Node 02 loop + code tools + permission gate + sandbox + worktree (TEXTBOOK §1)."""
from __future__ import annotations

import json
from pathlib import Path

from agentlab.agent.loop import LoopConfig, LoopResult, run_agent
from agentlab.costs import Budget
from agentlab.llm.types import ChatModel, Message
from agentlab.shopdev import fs_tools
from agentlab.shopdev.edit import edit_file
from agentlab.shopdev.gated import Approver, GatedExecutor, GateLogEntry
from agentlab.shopdev.permissions import PermissionGate
from agentlab.shopdev.sandbox import format_shell_result, make_sandbox
from agentlab.tools import Tool, ToolRegistry

SHOPDEV_SYSTEM = """You are shopdev, a careful software engineer working in a git checkout of the Shopfront project.
Workflow: (1) reproduce: find and run the relevant failing test; (2) read the code involved before editing it;
(3) make the smallest change that fixes the root cause; (4) re-run the failing test, then the related test files,
to check for regressions; (5) finish with a short report: root cause, the change, and the test results you saw.
Rules: never edit tests, test configuration or CI files; never special-case test inputs; the shell has no network
access; use `python -m pytest`. If a tool call is denied, don't try to get around the denial: choose another
approach or explain in your report why you're blocked."""


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def make_dev_tools(workspace: Path, sandbox) -> ToolRegistry:
    ws = Path(workspace)
    S = {"type": "string"}
    return ToolRegistry([
        Tool("read_file", "Read a text file with line numbers (cat -n style). Use offset/limit for long files. "
             "Line numbers are NOT part of the file content.",
             _obj({"path": S, "offset": {"type": "integer", "minimum": 1}, "limit": {"type": "integer", "minimum": 1,
                                                                                    "maximum": 2000}}, ["path"]),
             lambda path, offset=1, limit=400: fs_tools.read_file(ws, path, offset, limit)),
        Tool("list_dir", "List a directory (directories end with /). Defaults to the repo root.",
             _obj({"path": S}, []), lambda path=".": fs_tools.list_dir(ws, path)),
        Tool("grep", "Search file contents with a Python regex. Optional path (dir or file) and glob on file names "
             "(e.g. '*.py'). Returns path:line: text.",
             _obj({"pattern": S, "path": S, "glob": S}, ["pattern"]),
             lambda pattern, path=".", glob=None: fs_tools.grep(ws, pattern, path, glob)),
        Tool("write_file", "Create a NEW file. Fails if the file exists (use edit_file for existing files).",
             _obj({"path": S, "content": S}, ["path", "content"]),
             lambda path, content: fs_tools.write_file(ws, path, content), side_effects=True),
        Tool("edit_file", "Replace an exact snippet in an existing file. old_str must match the file EXACTLY "
             "(whitespace included) and be unique; read the file first and copy text without line numbers. "
             "Set replace_all to change every occurrence.",
             _obj({"path": S, "old_str": S, "new_str": S, "replace_all": {"type": "boolean"}},
                  ["path", "old_str", "new_str"]),
             lambda path, old_str, new_str, replace_all=False: edit_file(ws, path, old_str, new_str, replace_all),
             side_effects=True),
        Tool("run_shell", "Run a bash command in the repo root inside a sandbox with NO network. Use "
             "`python -m pytest ...` for tests. Output is truncated (head and tail kept).",
             _obj({"command": S, "timeout_s": {"type": "integer", "minimum": 1, "maximum": 600}}, ["command"]),
             lambda command, timeout_s=120: format_shell_result(sandbox.run(command, timeout_s)), side_effects=True),
    ])


def cli_approver(tool: str, args: dict, reason: str) -> bool:
    # show the FULL call: approving something you can't fully see isn't approval
    print(f"\n?? shopdev wants to run {tool}:\n{json.dumps(args, indent=2)}\n   gate says ASK: {reason}")
    return input("   approve? [y/N] ").strip().lower() == "y"


def run_shopdev(task: str, model: ChatModel, workspace: Path, *, sandbox=None, approver: Approver = cli_approver,
                budget: Budget | None = None, max_turns: int = 40) -> tuple[LoopResult, list[GateLogEntry]]:
    sandbox = sandbox or make_sandbox(workspace)
    gated = GatedExecutor(make_dev_tools(workspace, sandbox), PermissionGate(workspace), approver)
    system = SHOPDEV_SYSTEM
    agents_md = Path(workspace) / "AGENTS.md"
    if agents_md.is_file():   # project memory: the house rules every run starts with (TEXTBOOK §8)
        system += "\n\n# Project rules (AGENTS.md)\n" + agents_md.read_text()
    result = run_agent(model, system, [Message.user(task)], gated,
                       LoopConfig(max_turns=max_turns, max_tokens=8000, budget=budget, agent_name="shopdev"))
    return result, gated.log
