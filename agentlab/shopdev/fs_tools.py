"""Workspace-scoped file tools for shopdev. Errors are ToolErrors written for the model (TEXTBOOK §2)."""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from agentlab.shopdev.permissions import SECRET_GLOBS
from agentlab.tools.errors import ToolError

IGNORED_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache", "runs"}
MAX_LINE = 2000


def _resolve(workspace: Path, path: str) -> Path:
    ws = Path(workspace).resolve()
    p = (ws / path).resolve()
    # why: defence in depth; the permission gate checks too, but the tool must be safe on its own
    if not p.is_relative_to(ws):
        raise ToolError(f"{path} is outside the workspace.")
    return p


def _is_binary(p: Path) -> bool:
    with open(p, "rb") as f:
        return b"\0" in f.read(8192)


def read_file(workspace: Path, path: str, offset: int = 1, limit: int = 400) -> str:
    p = _resolve(workspace, path)
    if not p.exists():
        raise ToolError(f"{path} does not exist. Use list_dir or grep to find the right path.")
    if p.is_dir():
        raise ToolError(f"{path} is a directory. Use list_dir.")
    if _is_binary(p):
        raise ToolError(f"{path} looks like a binary file; not shown.")
    # split("\n"), not splitlines(): splitlines also breaks on \x0c and U+2028, which would skew line numbers
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return "[empty file]"
    offset = max(1, offset)
    chosen = lines[offset - 1: offset - 1 + limit]
    out = [f"{n:>6}\t{(l if len(l) <= MAX_LINE else l[:MAX_LINE] + '…[line truncated]')}"
           for n, l in enumerate(chosen, start=offset)]
    if offset > 1 or offset - 1 + limit < len(lines):
        out.append(f"[showing lines {offset}-{offset + len(chosen) - 1} of {len(lines)}; use offset/limit to see more]")
    return "\n".join(out)


def list_dir(workspace: Path, path: str = ".", max_entries: int = 200) -> str:
    p = _resolve(workspace, path)
    if not p.is_dir():
        raise ToolError(f"{path} is not a directory.")
    entries = sorted(e.name + ("/" if e.is_dir() else "") for e in p.iterdir() if e.name not in IGNORED_DIRS)
    shown = entries[:max_entries]
    if len(entries) > max_entries:
        shown.append(f"[{len(entries) - max_entries} more entries]")
    return "\n".join(shown) if shown else "[empty directory]"


def _walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        for f in sorted(filenames):
            yield Path(dirpath) / f


def grep(workspace: Path, pattern: str, path: str = ".", glob: str | None = None, max_results: int = 100) -> str:
    try:
        rx = re.compile(pattern)
    except re.error as e:
        raise ToolError(f"invalid regex {pattern!r}: {e}")
    ws = Path(workspace).resolve()
    root = _resolve(workspace, path)
    files = [root] if root.is_file() else sorted(_walk(root))
    out: list[str] = []
    for f in files:
        if glob and not fnmatch.fnmatch(f.name, glob):
            continue
        rf = f.resolve()
        if not rf.is_relative_to(ws):
            continue                       # symlink pointing outside: skip, don't follow
        rel = rf.relative_to(ws).as_posix().casefold()
        # why: a recursive grep must not become a way to read .env (the gate only sees the path argument)
        if any(fnmatch.fnmatch(rel, g.casefold()) or fnmatch.fnmatch(rf.name.casefold(), g.casefold())
               for g in SECRET_GLOBS):
            continue
        try:
            if _is_binary(f):
                continue
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                if len(out) == max_results:
                    out.append(f"[results truncated at {max_results}]")
                    return "\n".join(out)
                out.append(f"{rf.relative_to(ws).as_posix()}:{n}: {line.strip()[:300]}")
    return "\n".join(out) if out else "No matches."


def write_file(workspace: Path, path: str, content: str) -> str:
    p = _resolve(workspace, path)
    if p.exists():
        raise ToolError(f"{path} already exists. Use edit_file to change existing files.")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"Created {path} ({len(content.splitlines())} lines)."
