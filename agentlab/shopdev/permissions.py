r"""AGENT-OFF (reference solution): rule-based permission gate v1, hand-written in Node 03 YOU_DO task 3.

Read TEXTBOOK §4-§5 first. Tests: nodes/03-coding-agent/tests/test_permissions.py.
The rule lists below are GIVEN (you may extend them, but the tests assume at least these).

decide(tool, args) -> Decision(action, reason), action in {"allow", "ask", "deny"}.
All glob matching uses fnmatch.fnmatch on CASEFOLDED strings (macOS file systems are usually case-insensitive, so
".ENV" is ".env"). Note: fnmatch's * also matches "/". Rules, in this order:

FILE TOOLS (read_file, list_dir, grep -> "path" arg, default "."; edit_file, write_file -> "path" arg):
  1. Resolve workspace/path (following symlinks, so `..` and symlink escapes are caught). Outside the
     workspace -> deny.
  2. Relative path (posix) matching SECRET_GLOBS -> deny (all file tools, read or write). For grep, also deny if
     its "glob" argument matches SECRET_GLOBS (e.g. glob=".env").
  3. Write tools (edit_file, write_file): relative path matching PROTECTED_WRITE_GLOBS -> deny.
  4. Otherwise allow.

run_shell ("command" arg):
  1. Split into segments on &&, ||, |&, ;, |, a single & (background: NOT the & inside 2>&1 or >&), and newlines.
     A plain regex split is fine; it errs conservative:  r"&&|\|\||\|&|;|\||(?<![<>\d])&(?!>)|\n"
     Drop empty segments. Tokenize each with shlex.split; if tokenizing fails -> ask.
  2. DENY if any segment:
       - starts with a SHELL_DENY prefix (token tuple match, e.g. ("git", "push")), or
       - is `rm` with any flag token containing "r" or "f" (e.g. -rf, -r, -f, -fr, --recursive, --force), or
       - has a token (or the value part of a --opt=value token) that matches SECRET_GLOBS, either whole or by its
         basename (e.g. `cat .env`), or
       - has a token containing a shell glob character (* ? [) that, expanded in the workspace with
         glob.glob(token, root_dir=workspace, include_hidden=True), matches a secret (`cat .en?`), or
       - has a token (or --opt=value value) containing "~" at the start or ".." that resolves outside the workspace
         (expand "~" first), or one starting with "/" that resolves outside the workspace AND exists.
     Deny wins over everything else.
  3. ASK if the command contains "$" (variable expansion or substitution), "`", "<(" or ">(", or any segment:
       - has a token starting with "/" that resolves outside the workspace but does NOT exist (probably a pattern
         like "/products": the reason should suggest the grep tool), or
       - starts with an env assignment (first token contains "=" before any "/"), or
       - contains an output redirection: any token containing ">" except exactly "2>&1", or
       - has a token starting with "--output" (git log/diff/show --output=FILE writes files), or
       - starts with an ASK_INTERPRETERS prefix (python -c, bash -c, sh -c, eval, exec, source, ...), or
       - is `find` with -exec, -execdir, -delete, -ok, -fprint, -fprint0, -fprintf or -fls.
  4. ALLOW if every segment starts with a SHELL_ALLOW prefix.
  5. Otherwise ask.

Any other tool name -> ask.
Reasons should be short and specific (they are shown to the model on deny, and to the human on ask).

Know the limits (TEXTBOOK §5): allow-listing a command allows all of its flags, and edits + an allowed test run
let the agent execute any code it wrote. The gate keeps routine work smooth; the sandbox is the boundary.
"""
from __future__ import annotations

import fnmatch
import glob
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SECRET_GLOBS = [".env", ".env.*", "*/.env", "*/.env.*", ".envrc", "*/.envrc", "*.pem", "*.key", "*id_rsa*",
                "*id_ed25519*", "*.p12", "*credentials*", ".netrc", "*/.netrc"]
PROTECTED_WRITE_GLOBS = [
    # any tests directory or test file, anywhere (fnmatch's * spans "/"), plus grader/CI/config files
    "tests/*", "*/tests/*", "test_*.py", "*/test_*.py", "*_test.py", "conftest.py", "*/conftest.py",
    "pytest.ini", "*/pytest.ini", ".pytest.ini", "*/.pytest.ini", "tox.ini", "*/tox.ini", "setup.cfg", "*/setup.cfg",
    ".git", ".git/*", ".github/*", "pyproject.toml", "Makefile", "AGENTS.md", "CLAUDE.md",
    # course data and fixtures, and the agent's own safety code (it must not weaken its own gate)
    "data/*", "shopfront/seed.py", "shopfront/schema.sql", "shopfront/content/*", "shopfront/fixtures.md",
    "agentlab/llm/fake.py", "agentlab/shopdev/*",
    # persistence: things that run later, outside the agent's session
    ".claude/*", ".vscode/*", ".envrc", ".pre-commit-config.yaml", ".gitattributes",
]
SHELL_DENY = [
    ("curl",), ("wget",), ("ssh",), ("scp",), ("rsync",), ("nc",), ("ncat",), ("telnet",), ("ftp",),
    ("sudo",), ("su",), ("doas",),
    ("git", "push"), ("git", "remote"), ("git", "config"), ("git", "clean"), ("git", "reset", "--hard"),
    ("pip", "install"), ("pip3", "install"), ("uv", "pip", "install"), ("uv", "add"), ("npm",), ("npx",),
    ("git", "branch", "-D"), ("git", "branch", "-d"), ("git", "branch", "-f"), ("git", "branch", "-m"),
    ("git", "branch", "-M"), ("git", "update-ref"), ("git", "filter-branch"),
    ("chmod",), ("chown",), ("dd",), ("mkfs",), ("printenv",), ("env",), ("kill",), ("pkill",),
    ("shutdown",), ("reboot",), ("crontab",), ("docker",),
]
ASK_INTERPRETERS = [
    ("python", "-c"), ("python3", "-c"), (".venv/bin/python", "-c"), ("bash", "-c"), ("sh", "-c"), ("zsh", "-c"),
    ("eval",), ("exec",), ("source",), (".",), ("xargs",),
]
SHELL_ALLOW = [
    ("pytest",), ("python", "-m", "pytest"), ("python3", "-m", "pytest"), (".venv/bin/python", "-m", "pytest"),
    ("git", "status"), ("git", "diff"), ("git", "log"), ("git", "show"),
    ("ls",), ("cat",), ("head",), ("tail",), ("wc",), ("grep",), ("rg",), ("find",), ("pwd",), ("echo",),
    ("diff",), ("which",),
    # deliberately NOT here: sort (-o FILE), uniq (IN OUT), tree (-o FILE), git branch (-D): flags that write
]
FILE_READ_TOOLS = {"read_file", "list_dir", "grep"}
FILE_WRITE_TOOLS = {"edit_file", "write_file"}


@dataclass
class Decision:
    action: Literal["allow", "ask", "deny"]
    reason: str


class PermissionGate:
    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace).resolve()

    # ------------------------------------------------------------ helpers
    def _resolve(self, path: str) -> Path:
        return (self.workspace / os.path.expanduser(path)).resolve()

    def _rel(self, path: str) -> str | None:
        """Posix path relative to the workspace, or None if it resolves outside (symlinks followed)."""
        p = self._resolve(path)
        return p.relative_to(self.workspace).as_posix() if p.is_relative_to(self.workspace) else None

    @staticmethod
    def _matches(rel: str, globs: list[str]) -> bool:
        # why casefold: default macOS file systems are case-insensitive, so ".ENV" opens ".env"
        r = rel.casefold()
        return any(fnmatch.fnmatch(r, g.casefold()) for g in globs)

    def _secret(self, tok: str) -> bool:
        t = tok[2:] if tok.startswith("./") else tok
        return self._matches(t, SECRET_GLOBS) or self._matches(os.path.basename(t), SECRET_GLOBS)

    @staticmethod
    def _starts_with(tokens: list[str], prefixes: list[tuple]) -> bool:
        return any(tuple(tokens[:len(p)]) == p for p in prefixes)

    # ------------------------------------------------------------ decide
    def decide(self, tool: str, args: dict) -> Decision:
        if tool in FILE_READ_TOOLS or tool in FILE_WRITE_TOOLS:
            if tool == "grep" and args.get("glob") and self._matches(str(args["glob"]), SECRET_GLOBS):
                return Decision("deny", f"glob {args['glob']!r} targets secret files")
            return self._file(tool, str(args.get("path", ".")))
        if tool == "run_shell":
            return self._shell(str(args.get("command", "")))
        return Decision("ask", f"unknown tool {tool!r}")

    def _file(self, tool: str, path: str) -> Decision:
        rel = self._rel(path)
        if rel is None:
            return Decision("deny", f"{path} is outside the workspace")
        if self._matches(rel, SECRET_GLOBS):
            return Decision("deny", f"{rel} may contain secrets")          # the private-data leg (TEXTBOOK §4)
        if tool in FILE_WRITE_TOOLS and self._matches(rel, PROTECTED_WRITE_GLOBS):
            return Decision("deny", f"{rel} is protected (tests, config, data, CI): fix the code, not the checks")
        return Decision("allow", "read" if tool in FILE_READ_TOOLS else "edit inside the workspace (reviewable in git)")

    def _values(self, tokens: list[str]) -> list[str]:
        """Tokens plus the value part of --opt=value tokens: paths hide there too."""
        out = []
        for t in tokens:
            out.append(t)
            if t.startswith("-") and "=" in t:
                out.append(t.split("=", 1)[1])
        return out

    def _shell(self, command: str) -> Decision:
        segments = [s.strip() for s in re.split(r"&&|\|\||\|&|;|\||(?<![<>\d])&(?!>)|\n", command) if s.strip()]
        if not segments:
            return Decision("ask", "empty command")
        parsed: list[list[str]] = []
        for seg in segments:
            try:
                parsed.append(shlex.split(seg))
            except ValueError:
                return Decision("ask", f"could not parse {seg!r}")

        # 1) deny wins: check every segment before anything else (TEXTBOOK §5)
        unknown_abs: str | None = None
        for tokens in parsed:
            if not tokens:
                continue
            if self._starts_with(tokens, SHELL_DENY):
                return Decision("deny", f"{' '.join(tokens[:3])} is not allowed (network, privilege, destructive or install)")
            if tokens[0] == "rm" and any(t.startswith("-") and ("r" in t or "f" in t) for t in tokens[1:]):
                return Decision("deny", "recursive/forced rm is not allowed")
            for t in self._values(tokens):
                if self._secret(t):
                    return Decision("deny", f"{t} may contain secrets")
                if any(c in t for c in "*?["):
                    for hit in glob.glob(t, root_dir=self.workspace, include_hidden=True):
                        if self._secret(hit):
                            return Decision("deny", f"{t} expands to {hit}, which may contain secrets")
                if t.startswith("~") or ".." in t:
                    if self._rel(t) is None:
                        return Decision("deny", f"{t} is outside the workspace")
                elif t.startswith("/") and self._rel(t) is None:
                    if self._resolve(t).exists():
                        return Decision("deny", f"{t} is outside the workspace")
                    unknown_abs = unknown_abs or t

        # 2) ask for anything the rules can't see through
        if any(s in command for s in ("$", "`", "<(", ">(")):
            return Decision("ask", "variable expansion or command substitution")
        if unknown_abs:
            return Decision("ask", f"{unknown_abs} looks like a path outside the workspace; to search for a "
                                   f"pattern like this, use the grep tool")
        for tokens in parsed:
            if not tokens:
                continue
            first = tokens[0]
            if "=" in first.split("/")[0]:
                return Decision("ask", "environment assignment")
            if any(">" in t and t != "2>&1" for t in tokens):
                return Decision("ask", "output redirection writes files the gate can't see")
            if any(t.startswith("--output") for t in tokens):
                return Decision("ask", "--output writes a file")
            if self._starts_with(tokens, ASK_INTERPRETERS):
                return Decision("ask", f"{' '.join(tokens[:2])} runs arbitrary code")
            if first == "find" and any(t in ("-exec", "-execdir", "-delete", "-ok", "-fprint", "-fprint0",
                                             "-fprintf", "-fls") for t in tokens):
                return Decision("ask", "find with side effects")

        # 3) allow only if EVERY segment is known-safe
        if all(self._starts_with(t, SHELL_ALLOW) for t in parsed if t):
            return Decision("allow", "known-safe command")
        return Decision("ask", "not on the allow-list")
