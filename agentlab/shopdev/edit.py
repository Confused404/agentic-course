"""AGENT-OFF: the search-and-replace edit tool. You write `edit_file` by hand (Node 03 YOU_DO task 2).

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
  directory, then os.replace() it over the original. Preserve everything else byte-for-byte (newline style included)
  and keep the file's permission bits (shutil.copymode). Read and write as UTF-8.
- Return: f"Edited {path}: replaced {n} occurrence(s).\n" followed by a snippet of the NEW file: lines from 3 before
  to 3 after the first replaced region, each formatted as f"{lineno:>6}\t{text}" (1-based, like cat -n).
"""
from __future__ import annotations

from pathlib import Path

from agentlab.tools.errors import ToolError


class EditError(ToolError):
    """An edit the model must fix (bad path, no match, ambiguous match). Reported to the model, not raised to you."""


def edit_file(workspace: Path, path: str, old_str: str, new_str: str, replace_all: bool = False) -> str:
    raise NotImplementedError("AGENT-OFF: implement by hand (Node 03 YOU_DO task 2)")
