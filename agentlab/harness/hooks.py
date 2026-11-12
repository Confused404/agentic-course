"""Hooks: deterministic code that runs at fixed points of the agent's work (TEXTBOOK §5).

A hook is not a request to the model; it always runs. Pre-tool hooks can block a call (with a reason the model
reads), post-tool hooks can add feedback to a result, and a stop hook can refuse to let the session end.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from agentlab.llm.types import ToolResultBlock, ToolSpec, ToolUseBlock

PreHook = Callable[[str, dict], str | None]                 # (tool, args) -> deny reason or None
PostHook = Callable[[str, dict, ToolResultBlock], str | None]   # -> feedback to append, or None


@dataclass
class HookedExecutor:
    inner: object                                  # any ToolExecutor (here: the gated shopdev tools)
    pre: list[PreHook] = field(default_factory=list)
    post: list[PostHook] = field(default_factory=list)
    events: list[str] = field(default_factory=list)

    def specs(self) -> list[ToolSpec]:
        return self.inner.specs()

    def execute(self, call: ToolUseBlock) -> ToolResultBlock:
        for hook in self.pre:
            reason = hook(call.name, call.input)
            if reason:
                self.events.append(f"pre-hook denied {call.name}: {reason}")
                return ToolResultBlock(call.id, f"Blocked by a project hook: {reason}", is_error=True)
        res = self.inner.execute(call)
        notes = [n for hook in self.post if (n := hook(call.name, call.input, res))]
        if notes:
            self.events.append(f"post-hook on {call.name}: {notes[0][:80]}")
            res = ToolResultBlock(res.tool_use_id, res.text + "\n\n[hook] " + "\n[hook] ".join(notes),
                                  is_error=res.is_error)
        return res


_WRITEY = re.compile(r"(>>?|\bsed\s+-i\b|\brm\b|\bmv\b|\bcp\b|\btee\b|\btruncate\b|\bgit\s+(checkout|restore|rm)\b)")


def protect_in_shell(protected: list[str]) -> PreHook:
    """Deny shell commands that mention a protected file together with something that writes. why: the permission
    gate guards the FILE tools; the shell is the side door (Node 03 §5)."""
    def hook(tool: str, args: dict) -> str | None:
        if tool != "run_shell":
            return None
        cmd = str(args.get("command", ""))
        hits = [p for p in protected if p in cmd]
        if hits and _WRITEY.search(cmd):
            return f"{hits[0]} is protected; change the code, not the tests or the progress file"
        return None
    return hook


def syntax_check(workspace: Path) -> PostHook:
    """After a .py file is written or edited, compile it and report a syntax error immediately (a cheap, certain
    check beats waiting for the test run)."""
    def hook(tool: str, args: dict, res: ToolResultBlock) -> str | None:
        path = str(args.get("path", ""))
        if tool not in ("write_file", "edit_file") or res.is_error or not path.endswith(".py"):
            return None
        r = subprocess.run([sys.executable, "-m", "py_compile", str(Path(workspace) / path)], capture_output=True,
                           text=True, timeout=30)
        return None if r.returncode == 0 else f"{path} no longer compiles: {(r.stderr or r.stdout).strip()[-400:]}"
    return hook
