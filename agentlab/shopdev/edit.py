"""AGENT-OFF (reference solution): the search-and-replace edit tool, hand-written in Node 03 YOU_DO task 2.

Read TEXTBOOK §2 first. Tests: nodes/03-coding-agent/tests/test_edit.py.

Contract for edit_file(workspace, path, old_str, new_str, replace_all=False) -> str:
- `path` is relative to `workspace` (absolute paths are allowed only if they are inside it). Resolve it
  (following symlinks); if the result is outside the workspace -> EditError mentioning "outside".
- File must exist (else EditError suggesting write_file). old_str must be non-empty, and old_str != new_str.
- Count EXACT occurrences of old_str in the file text:
    0 -> EditError "old_str not found in <path>". If old_str matches when whitespace is collapsed on both sides
         (every run of whitespace -> one space), add a hint naming the 1-based line where that loose match starts
         and saying to check indentation/whitespace.
    >1 and not replace_all -> EditError that gives the count and the 1-based starting line of each match, and
         suggests adding surrounding context or replace_all=True.
- Replace (all occurrences if replace_all, else the single one). Write atomically: write a temp file in the same
  directory, then os.replace() it over the original. Preserve everything else byte-for-byte (newline style included).
- Return: f"Edited {path}: replaced {n} occurrence(s).\n" followed by a snippet of the NEW file: lines from 3 before
  to 3 after the first replaced region, each formatted as f"{lineno:>6}\t{text}" (1-based, like cat -n).
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

from agentlab.tools.errors import ToolError


class EditError(ToolError):
    """An edit the model must fix (bad path, no match, ambiguous match). Reported to the model, not raised to you."""


def _resolve(workspace: Path, path: str) -> Path:
    ws = Path(workspace).resolve()
    p = (ws / path).resolve()          # why: resolve() follows symlinks and collapses "..", so escapes are visible
    if not p.is_relative_to(ws):
        raise EditError(f"{path} is outside the workspace; you can only edit files inside it.")
    return p


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _loose_match_line(text: str, needle: str) -> int | None:
    """1-based line where needle matches if every whitespace run is treated as one space, else None."""
    words = needle.split()
    if not words:
        return None
    pattern = r"\s+".join(re.escape(w) for w in words)
    m = re.search(pattern, text)
    return _line_of(text, m.start()) if m else None


def edit_file(workspace: Path, path: str, old_str: str, new_str: str, replace_all: bool = False) -> str:
    p = _resolve(workspace, path)
    if not p.is_file():
        raise EditError(f"{path} does not exist. Use write_file to create a new file.")
    if not old_str:
        raise EditError("old_str is empty. Give the exact text to replace (read the file first).")
    if old_str == new_str:
        raise EditError("old_str and new_str are identical; nothing to change.")
    with open(p, newline="", encoding="utf-8") as f:      # newline="": keep \r\n exactly as it is
        text = f.read()

    starts = [m.start() for m in re.finditer(re.escape(old_str), text)]
    if not starts:
        msg = f"old_str not found in {path}."
        loose = _loose_match_line(text, old_str)
        if loose is not None:
            msg += (f" A match ignoring whitespace starts at line {loose}: check indentation/whitespace and copy "
                    f"the text exactly from read_file output (without the line-number prefix).")
        raise EditError(msg)
    if len(starts) > 1 and not replace_all:
        lines = ", ".join(str(_line_of(text, s)) for s in starts)
        raise EditError(f"old_str matches {len(starts)} times in {path} (lines {lines}). Include more surrounding "
                        f"context to make it unique, or pass replace_all=True to change every occurrence.")

    n = len(starts) if replace_all else 1
    new_text = text.replace(old_str, new_str) if replace_all else text.replace(old_str, new_str, 1)
    # why atomic: a crash mid-write must never leave a half-written source file
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            f.write(new_text)
        shutil.copymode(p, tmp)          # mkstemp creates 0600; keep the original permissions
        os.replace(tmp, p)
    except BaseException:
        os.unlink(tmp)
        raise

    first_line = _line_of(new_text, starts[0])
    last_line = first_line + new_str.count("\n")
    lines = new_text.split("\n")
    lo, hi = max(1, first_line - 3), min(len(lines), last_line + 3)
    snippet = "\n".join(f"{i:>6}\t{lines[i - 1]}" for i in range(lo, hi + 1))
    return f"Edited {path}: replaced {n} occurrence(s).\n{snippet}"
