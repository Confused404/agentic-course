"""python -m agentlab.shopdev "fix the failing pricing tests in nodes/03-coding-agent/tests/test_seeded_bugs.py" """
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from agentlab.config import ROOT
from agentlab.costs import Budget
from agentlab.llm.registry import get_model
from agentlab.shopdev.agent import run_shopdev
from agentlab.shopdev.sandbox import make_sandbox
from agentlab.shopdev.workspace import create_worktree, diff


def main() -> None:
    ap = argparse.ArgumentParser(prog="shopdev")
    ap.add_argument("task")
    ap.add_argument("--model", default="mid")
    ap.add_argument("--budget", type=float, default=1.0)
    ap.add_argument("--workspace", type=Path)
    ap.add_argument("--sandbox", choices=["docker", "local"], default="docker")
    ap.add_argument("--max-turns", type=int, default=40)
    a = ap.parse_args()

    name = time.strftime("%Y%m%d-%H%M%S")
    ws = a.workspace or create_worktree(ROOT, name)
    print(f"workspace: {ws}")
    if (Path(ws) / ".env").exists():
        print("! WARNING: this workspace contains .env. A fresh worktree wouldn't (it only has tracked files).")
    budget = Budget(limit_usd=a.budget, label="shopdev")
    sandbox = make_sandbox(ws, prefer=a.sandbox, venv=Path(sys.prefix))
    result, log = run_shopdev(a.task, get_model(a.model), ws, sandbox=sandbox, budget=budget, max_turns=a.max_turns)

    print(f"\n=== stop: {result.stop} after {result.turns} turns, ${budget.spent_usd:.4f} ===")
    print(result.final_text)
    print("\n=== gate log ===")
    for e in log:
        detail = str(e.args.get("command") or e.args.get("path") or "")[:70]
        print(f"{e.action:5} {'(approved)' if e.approved else '(refused)' if e.approved is False else '':10} "
              f"{e.tool:10} {detail}")
    print("\n=== diff ===")
    print(diff(ws) or "(no changes)")
    print("\nshopdev does not commit. To keep the change:")
    print(f"  git -C {ws} add -A && git -C {ws} commit -m 'shopdev: {a.task[:50]}'")
    print("  git merge <the worktree's branch>        # from your own branch")
    print(f"To discard: git worktree remove --force {ws}")


if __name__ == "__main__":
    main()
