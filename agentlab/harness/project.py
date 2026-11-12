"""GIVEN: the practice project (promo) workspaces, checkpoints, and the hidden acceptance tests (Node 12).

A workspace is a fresh copy of nodes/12-harness/project_template/ in its own git repository. The acceptance tests
live OUTSIDE it (nodes/12-harness/acceptance/), so the agent can't read, run or edit them: they're the harness's
ground truth, not the agent's.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from agentlab.config import ROOT

NODE = ROOT / "nodes" / "12-harness"
TEMPLATE = NODE / "project_template"
ACCEPTANCE = NODE / "acceptance"
FEATURES = ("F1", "F2", "F3", "F4", "F5")


def _git(ws: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "harness", "GIT_AUTHOR_EMAIL": "harness@example.invalid",
           "GIT_COMMITTER_NAME": "harness", "GIT_COMMITTER_EMAIL": "harness@example.invalid"}
    r = subprocess.run(["git", *args], cwd=ws, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def new_workspace(dest: Path) -> Path:
    """Copy the template to `dest` (must not exist) and commit it as the starting point."""
    dest = Path(dest)
    if dest.exists():
        raise FileExistsError(dest)
    if not TEMPLATE.is_dir():
        raise FileNotFoundError(f"template not found: {TEMPLATE}")
    shutil.copytree(TEMPLATE, dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    _git(dest, "init", "-q", "-b", "main")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "start: promo template")
    return dest


def checkpoint(ws: Path, message: str) -> str | None:
    """Commit everything; returns the new commit id, or None if nothing changed."""
    _git(ws, "add", "-A")
    if not _git(ws, "status", "--porcelain").strip():
        return None
    _git(ws, "commit", "-q", "-m", message)
    return _git(ws, "rev-parse", "HEAD").strip()


def head(ws: Path) -> str:
    return _git(ws, "rev-parse", "HEAD").strip()


def reset_to(ws: Path, commit: str) -> None:
    """Throw away everything after `commit` (tracked and untracked)."""
    _git(ws, "reset", "-q", "--hard", commit)
    _git(ws, "clean", "-q", "-fd")


def diff_since(ws: Path, commit: str) -> str:
    _git(ws, "add", "-A")
    return _git(ws, "diff", "--cached", commit)


def changed_files(ws: Path, commit: str) -> list[str]:
    _git(ws, "add", "-A")
    return [x for x in _git(ws, "diff", "--cached", "--name-only", commit).splitlines() if x]


def run_visible_tests(ws: Path, timeout_s: int = 180) -> tuple[bool, str]:
    """The workspace's own tests (the ones the agent can see and write), run by the harness."""
    # why -I (isolated mode): `python -m` normally puts the current directory first on sys.path, so a workspace
    # file named pytest.py would BE pytest and could print "5 passed". -I keeps the cwd (and PYTHONPATH) out; the
    # workspace's root conftest.py still makes `promo` importable, the way pytest intends.
    r = subprocess.run([sys.executable, "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x", "--no-header"],
                       cwd=ws, capture_output=True, text=True, timeout=timeout_s,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    return r.returncode == 0, (r.stdout + r.stderr)[-4000:]


def run_acceptance(ws: Path, timeout_s: int = 180) -> dict[str, dict]:
    """Hidden acceptance tests, per feature: {"F1": {"passed": bool, "failed": n, "total": n}, ...}."""
    out: dict[str, dict] = {}
    for f in FEATURES:
        path = ACCEPTANCE / f"test_{f.lower()}.py"
        # why cwd=ACCEPTANCE and -I: nothing in the workspace runs before the acceptance conftest has put the
        # acceptance directory ahead of it on sys.path (see the Node 12 review: a workspace pytest.py)
        r = subprocess.run([sys.executable, "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header",
                            "--rootdir", str(ACCEPTANCE), "-c", os.devnull, str(path)],
                           cwd=ACCEPTANCE, capture_output=True, text=True, timeout=timeout_s,
                           env={**os.environ, "PROMO_WORKSPACE": str(Path(ws).resolve()),
                                "PYTHONDONTWRITEBYTECODE": "1"})
        text = r.stdout + r.stderr
        passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", text)) else 0
        failed = sum(int(x) for x in re.findall(r"(\d+) (?:failed|error)", text))
        out[f] = {"passed": r.returncode == 0 and failed == 0 and passed > 0, "failed": failed,
                  "total": passed + failed}
    return out


SUSPICIOUS_NAMES = ("pytest.py", "_pytest.py", "sitecustomize.py", "usercustomize.py", "conftest.py")


def suspicious_files(ws: Path, since: str) -> list[str]:
    """Changed files that could change how tests run rather than what the code does: Python files outside promo/
    and tests/ (e.g. a fake pytest.py), .pth files, any conftest.py. why: tests are the harness's evidence, and
    these files can forge it."""
    out = []
    for f in changed_files(ws, since):
        name = Path(f).name
        inside = f.startswith(("promo/", "tests/"))
        if name in SUSPICIOUS_NAMES or f.endswith(".pth") or (f.endswith(".py") and not inside):
            out.append(f)
    return sorted(out)


def read_features(ws: Path) -> list[dict]:
    return json.loads((Path(ws) / "features.json").read_text())
