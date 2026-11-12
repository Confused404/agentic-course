# SPEC: Node 03: `shopdev`, a small coding agent

**For the coding agent.** Read `AGENTS.md`. Background: TEXTBOOK §1–§8.
**AGENT-OFF (the learner's, don't implement or substitute):** `agentlab/shopdev/edit.py::edit_file` and
`agentlab/shopdev/permissions.py::PermissionGate.decide`. Your code *calls* them. Their tests stay red until the
learner writes them. **Do not touch** `shopfront/pricing.py`, `reports.py`, `search.py`: `shopdev` fixes those, not you.

## Files
```
modify  agentlab/tools/base.py            ToolError handling (1)
create  agentlab/shopdev/__init__.py
create  agentlab/shopdev/fs_tools.py      (2)
create  agentlab/shopdev/sandbox.py       (3)
create  agentlab/shopdev/workspace.py     (4)
create  agentlab/shopdev/gated.py         (5)
create  agentlab/shopdev/agent.py         (6)
create  agentlab/shopdev/__main__.py      (7)
create  docker/shopdev.Dockerfile         (8)
```

## 1. ToolError in the registry
In `ToolRegistry.execute`, catch `agentlab.tools.errors.ToolError` (given) **before** the generic handler and return
`ToolResultBlock(call.id, str(e), is_error=True)`, i.e. the bare message. Re-export `ToolError` from `agentlab.tools`.

## 2. `fs_tools.py`: workspace-scoped file tools
All take `workspace: Path` first, accept paths relative to it, and raise `ToolError` with an actionable message on
failure (outside the workspace, not found, is a directory, …). Path resolution follows symlinks; refuse anything
that resolves outside the workspace (defence in depth: the gate checks too).
```python
IGNORED_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache", "runs"}

def read_file(workspace: Path, path: str, offset: int = 1, limit: int = 400) -> str
```
Lines `offset .. offset+limit-1` (1-based), each formatted `f"{n:>6}\t{line}"`. Lines longer than 2,000 chars are cut
with `"…[line truncated]"`. If not all lines were shown, append a final line
`f"[showing lines {a}-{b} of {total}; use offset/limit to see more]"`. Empty file → `"[empty file]"`. Binary files
(a NUL byte in the first 8 KB) → ToolError.
```python
def list_dir(workspace: Path, path: str = ".", max_entries: int = 200) -> str
```
Sorted entry names, one per line, directories with a trailing `/`, skipping IGNORED_DIRS. If more than `max_entries`,
show the first `max_entries` and a final line `f"[{total - max_entries} more entries]"`.
```python
def grep(workspace: Path, pattern: str, path: str = ".", glob: str | None = None, max_results: int = 100) -> str
```
Python regex (invalid regex → ToolError). Recursive under `path`, skipping IGNORED_DIRS and binary files; if `glob` is
given, only files whose *name* matches it (`fnmatch`). **Skip** files that resolve outside the workspace (symlinks)
and files whose relative path or name matches `agentlab.shopdev.permissions.SECRET_GLOBS` (casefolded): a recursive
grep must not become a way to read `.env`. (The constants are given; only `decide()` is AGENT-OFF.)
Number lines with `text.split("\n")` (not `splitlines()`, which also splits on `\x0c` and U+2028); same for `read_file`. Output lines `f"{relpath}:{lineno}: {line.strip()[:300]}"` in
sorted file order; at most `max_results`, then `f"[results truncated at {max_results}]"`. No matches →
`"No matches."`.
```python
def write_file(workspace: Path, path: str, content: str) -> str
```
Create a NEW file (parents created). If it exists → ToolError telling the model to use `edit_file` instead. Returns
`f"Created {path} ({n} lines)."`.

## 3. `sandbox.py`
```python
@dataclass
class ShellResult:
    exit_code: int | None      # None if killed by timeout
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float

def truncate_output(text: str, limit: int = 10_000) -> str
    # <= limit: unchanged. Else first 6_000 chars + f"\n[... {omitted} chars omitted ...]\n" + last 4_000 chars
    # (scale head/tail as 60%/40% of `limit`). Why head+tail: test failures summarise at the END.
def format_shell_result(r: ShellResult, limit: int = 10_000) -> str
    # f"exit code: {r.exit_code}" (or "TIMED OUT after {duration:.0f}s"), then "--- stdout ---\n" + truncated stdout,
    # then "--- stderr ---\n" + truncated stderr (omit a section if empty).

class LocalSandbox:          # level-1 isolation (TEXTBOOK §6). Honest name: it is NOT a security boundary.
    def __init__(self, workspace: Path, venv: Path | None = None, memory_mb: int = 2048, cpu_seconds: int = 300)
    def run(self, command: str, timeout_s: int = 120) -> ShellResult
```
`LocalSandbox.run`: `subprocess.Popen(["bash", "-c", limits + command], cwd=workspace, stdin=DEVNULL, stdout=PIPE,
stderr=PIPE, text=True, start_new_session=True)` then `communicate(timeout=timeout_s)`, with:
- a **scrubbed environment**: only `PATH`, `LANG`, `LC_ALL`, `TERM`, `TMPDIR` from the parent, plus
  `PYTHONDONTWRITEBYTECODE=1` and `HOME=<a temp dir created in __init__>` (never your real home: `~/.ssh`,
  `~/.bashrc`). If `venv` is given, prepend `venv/bin` to PATH. **No** API keys or other variables leak in.
- `stdin=subprocess.DEVNULL`: a bare `cat` or an `input()` must not block, or steal the keystrokes meant for the
  approval prompt.
- limits as a shell prefix, not `preexec_fn` (which is unsafe in threaded programs):
  `limits = f"ulimit -v {memory_mb*1024} 2>/dev/null; ulimit -t {cpu_seconds} 2>/dev/null; "`.
- on timeout: `os.killpg(proc.pid, SIGKILL)` (it's its own session), then `communicate(timeout=5)` (a daemonized
  grandchild may hold the pipes; if so return empty output), and return `timed_out=True, exit_code=None`.
```python
class DockerSandbox:         # level-2 isolation
    def __init__(self, workspace: Path, image: str = "agentic-course/shopdev:latest", memory: str = "1g",
                 cpus: str = "1", pids: int = 256, network: bool = False)
    def command_line(self, command: str) -> list[str]     # pure: the argv for `docker run` (tested offline)
    def run(self, command: str, timeout_s: int = 120) -> ShellResult
def docker_available() -> bool                           # `docker info` returns 0 within 5 s
def make_sandbox(workspace: Path, prefer: str = "docker", venv: Path | None = None) -> LocalSandbox | DockerSandbox
    # docker if prefer == "docker" and docker_available(), else LocalSandbox (print a one-line warning when falling back)
```
`command_line` must produce: `docker run --rm --pull never --network none` (omit `--network none` only if
`network=True`; `--pull never` stops a same-named public image from being fetched)
`--memory <m> --cpus <c> --pids-limit <p> --cap-drop ALL --security-opt no-new-privileges`
`--user <uid>:<gid>` (current user's, so files stay yours) `-e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1`
`-v <workspace>:/work -w /work <image> bash -c <command>`. No other `-e` flags (no secrets).
`run` uses `subprocess.run(argv, ..., stdin=subprocess.DEVNULL)` with the timeout; on timeout, run `docker kill` on a
container name you assigned with `--name shopdev-<uuid>` (add `--name` to the argv in `run`, not in `command_line`).
`make_sandbox` uses Docker only if the daemon is up **and** `docker image inspect <image>` succeeds.

## 4. `workspace.py`
```python
def create_worktree(repo: Path, name: str) -> Path
    # `git -C repo worktree add -b shopdev/<name> <repo>/../<repo.name>-shopdev-<name> HEAD`; returns the path.
    # If the branch exists, raise ValueError. (git must be installed.)
def diff(workspace: Path) -> str          # `git -C workspace diff` plus untracked files listed as "?? path"
def remove_worktree(repo: Path, workspace: Path, delete_branch: bool = False) -> None
```

## 5. `gated.py`: put the gate in front of the tools
```python
Approver = Callable[[str, dict, str], bool]     # (tool_name, args, reason) -> approved?

@dataclass
class GateLogEntry:
    tool: str
    args: dict
    action: str          # allow | ask | deny
    reason: str
    approved: bool | None   # for ask: the human's answer; else None

class GatedExecutor:      # implements agentlab.agent.loop.ToolExecutor
    def __init__(self, registry: ToolRegistry, gate: PermissionGate, approver: Approver)
    log: list[GateLogEntry]
    def specs(self) -> list[ToolSpec]          # = registry.specs()
    def execute(self, call: ToolUseBlock) -> ToolResultBlock
```
`execute`: `decision = gate.decide(call.name, call.input)`. deny → error result `f"Denied by policy: {reason}"`,
ask → call `approver(name, input, reason)` (if the approver raises, e.g. EOFError with no terminal, treat it as
refused); if False → error result
`f"Denied by the user: {reason}. Try a different approach or explain why this is needed."`; allow (or approved) →
`registry.execute(call)`. Log every decision. If `gate.decide` raises, treat it as deny with reason
`"permission check failed"` (fail closed).

## 6. `agent.py`
```python
SHOPDEV_SYSTEM: str      # see below
def make_dev_tools(workspace: Path, sandbox) -> ToolRegistry
def cli_approver(tool: str, args: dict, reason: str) -> bool     # prints the FULL call (no truncation) + reason, asks y/N
def run_shopdev(task: str, model: ChatModel, workspace: Path, *, sandbox=None, approver: Approver = cli_approver,
                budget: Budget | None = None, max_turns: int = 40) -> tuple[LoopResult, list[GateLogEntry]]
```
Tools (all through `agentlab.tools.Tool`, schemas with `additionalProperties: false`):
`read_file(path, offset?, limit?)`, `list_dir(path?)`, `grep(pattern, path?, glob?)`, `write_file(path, content)`,
`edit_file(path, old_str, new_str, replace_all?)` (calls the learner's `edit.edit_file(workspace, ...)`),
`run_shell(command, timeout_s?)` (integer 1–600, default 120; returns `format_shell_result(sandbox.run(...))`).
Descriptions must state the key rules (edit_file: exact unique match, read first; run_shell: no network, use
`python -m pytest`; write_file: new files only).
`run_shopdev`: `sandbox = sandbox or make_sandbox(workspace)`; build the tools; wrap them in
`GatedExecutor(tools, PermissionGate(workspace), approver)`; system prompt = `SHOPDEV_SYSTEM`, plus
`"\n\n# Project rules (AGENTS.md)\n" + <contents>` if `workspace/AGENTS.md` exists (project memory, TEXTBOOK §8);
call `run_agent(model, system, [Message.user(task)],
gated, LoopConfig(max_turns=max_turns, max_tokens=8000, budget=budget, agent_name="shopdev"))`. Return the result and
the gate log.
`SHOPDEV_SYSTEM` (keep this content; wording can be tightened):
```
You are shopdev, a careful software engineer working in a git checkout of the Shopfront project.
Workflow: (1) reproduce: find and run the relevant failing test; (2) read the code involved before editing it;
(3) make the smallest change that fixes the root cause; (4) re-run the failing test, then the related test files,
to check for regressions; (5) finish with a short report: root cause, the change, and the test results you saw.
Rules: never edit tests, test configuration or CI files; never special-case test inputs; the shell has no network
access; use `python -m pytest`. If a tool call is denied, don't try to get around the denial: choose another
approach or explain in your report why you're blocked.
```

## 7. `__main__.py`: `python -m agentlab.shopdev "<task>" [options]`
Options: `--model ALIAS` (default `mid`), `--budget USD` (default 1.0), `--workspace PATH` (default: create a new
worktree named with a timestamp), `--sandbox docker|local` (default docker, falling back), `--max-turns N` (40).
At the start, warn if the workspace contains `.env` (a fresh worktree wouldn't). At the end print: the loop's stop and
turn count, cost, the gate log as a table (tool, action, approved), and `diff(workspace)`. shopdev never commits, so
print the exact commands to keep the change (`git -C <ws> add -A && git -C <ws> commit -m ...`, then merge the branch)
or discard it (`git worktree remove --force <ws>`).

## 8. `docker/shopdev.Dockerfile`
`FROM python:3.12-slim`, install `git`, copy only `pyproject.toml` and install the project's dependencies (plus the
`dev` extra) system-wide with pip (no project source in the image: the workspace is mounted at run time), `WORKDIR /work`.
Add a comment with the build command: `docker build -t agentic-course/shopdev:latest -f docker/shopdev.Dockerfile .`

## Done when
`make grade N=03` passes **except** these expected-red tests: `test_edit.py`, `test_permissions.py`,
`test_shopdev_agent.py::test_fix_a_bug_end_to_end`, `test_shopdev_agent.py::test_gate_blocks_test_edits_secrets_and_asks`
(all need the learner's AGENT-OFF code) and `test_seeded_bugs.py` (fixed later by `shopdev` itself, not by you).
Everything else, including `test_shopdev_agent.py::test_tools_registered`, must be green. `git diff main -- shopfront/`
must be empty. Explain your diff.
