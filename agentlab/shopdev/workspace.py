"""Isolated, reviewable workspaces for shopdev: one git worktree + branch per task (TEXTBOOK §7)."""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout


def create_worktree(repo: Path, name: str) -> Path:
    repo = Path(repo).resolve()
    branch = f"shopdev/{name}"
    if _git("branch", "--list", branch, cwd=repo).strip():
        raise ValueError(f"branch {branch} already exists")
    path = repo.parent / f"{repo.name}-shopdev-{name}"
    _git("worktree", "add", "-q", "-b", branch, str(path), "HEAD", cwd=repo)
    return path


def diff(workspace: Path) -> str:
    tracked = _git("diff", cwd=workspace)
    untracked = _git("ls-files", "--others", "--exclude-standard", cwd=workspace).split()
    return tracked + "".join(f"?? {u}\n" for u in untracked)


def remove_worktree(repo: Path, workspace: Path, delete_branch: bool = False) -> None:
    branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=workspace).strip()
    _git("worktree", "remove", "--force", str(workspace), cwd=repo)
    if delete_branch:
        _git("branch", "-D", branch, cwd=repo)
