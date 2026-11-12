"""Worktree isolation and the gated executor (with a fake gate, so this doesn't depend on AGENT-OFF code)."""
import subprocess

import pytest

from agentlab.llm.types import ToolUseBlock
from agentlab.shopdev.gated import GatedExecutor
from agentlab.shopdev.permissions import Decision
from agentlab.shopdev.workspace import create_worktree, diff, remove_worktree
from agentlab.tools import Tool, ToolRegistry


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "proj"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "t")
    (r / "a.py").write_text("x = 1\n")
    git(r, "add", ".")
    git(r, "commit", "-qm", "init")
    return r


def test_worktree_lifecycle(repo):
    ws = create_worktree(repo, "t1")
    assert ws.exists() and ws != repo and (ws / "a.py").read_text() == "x = 1\n"
    assert "shopdev/t1" in git(repo, "branch", "--list", "shopdev/t1")
    (ws / "a.py").write_text("x = 2\n")
    (ws / "new.py").write_text("y\n")
    d = diff(ws)
    assert "-x = 1" in d and "+x = 2" in d and "?? new.py" in d
    assert (repo / "a.py").read_text() == "x = 1\n", "your checkout is untouched"
    with pytest.raises(ValueError):
        create_worktree(repo, "t1")
    remove_worktree(repo, ws, delete_branch=True)
    assert not ws.exists() and "shopdev/t1" not in git(repo, "branch", "--list")


class FakeGate:
    def __init__(self, table):
        self.table = table

    def decide(self, tool, args):
        if tool == "explode":
            raise RuntimeError("bug in gate")
        return Decision(*self.table[tool])


def registry(calls):
    def mk(name):
        return Tool(name, name, {"type": "object", "properties": {}}, lambda: calls.append(name) or f"{name} ran")
    return ToolRegistry([mk("safe"), mk("risky"), mk("evil"), mk("explode")])


def test_gated_executor_paths():
    calls, answers = [], []
    gate = FakeGate({"safe": ("allow", "read only"), "risky": ("ask", "unknown command"), "evil": ("deny", "network")})

    def approver(tool, args, reason):
        answers.append((tool, reason))
        return tool == "risky" and len(answers) == 1      # approve the first ask, refuse the second
    ex = GatedExecutor(registry(calls), gate, approver)
    assert [s.name for s in ex.specs()] == ["evil", "explode", "risky", "safe"]
    r = [ex.execute(ToolUseBlock(f"t{i}", n, {})) for i, n in enumerate(["safe", "risky", "risky", "evil", "explode"])]
    assert [x.is_error for x in r] == [False, False, True, True, True]
    assert calls == ["safe", "risky"], "denied / refused / failed-closed calls never run"
    assert r[2].content.startswith("Denied by the user") and r[3].content == "Denied by policy: network"
    assert "permission check failed" in r[4].content
    def crashing_approver(*a):
        raise EOFError("no terminal")
    ex2 = GatedExecutor(registry([]), gate, crashing_approver)
    assert ex2.execute(ToolUseBlock("x", "risky", {})).is_error and ex2.log[0].approved is False
    assert [(e.tool, e.action, e.approved) for e in ex.log] == [
        ("safe", "allow", None), ("risky", "ask", True), ("risky", "ask", False), ("evil", "deny", None),
        ("explode", "deny", None)]
