"""Where shopdev's shell commands run. Two levels from TEXTBOOK §6: LocalSandbox (process limits, scrubbed env:
NOT a security boundary) and DockerSandbox (container: no network, dropped caps, non-root, only the workspace)."""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

KEEP_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TERM", "TMPDIR")


@dataclass
class ShellResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float


def truncate_output(text: str, limit: int = 10_000) -> str:
    if len(text) <= limit:
        return text
    head, tail = int(limit * 0.6), int(limit * 0.4)
    # why head AND tail: pytest prints the failure summary at the END (TEXTBOOK §2)
    return f"{text[:head]}\n[... {len(text) - head - tail} chars omitted ...]\n{text[-tail:]}"


def format_shell_result(r: ShellResult, limit: int = 10_000) -> str:
    parts = [f"TIMED OUT after {r.duration_s:.0f}s" if r.timed_out else f"exit code: {r.exit_code}"]
    if r.stdout:
        parts.append("--- stdout ---\n" + truncate_output(r.stdout, limit))
    if r.stderr:
        parts.append("--- stderr ---\n" + truncate_output(r.stderr, limit))
    return "\n".join(parts)


class LocalSandbox:
    def __init__(self, workspace: Path, venv: Path | None = None, memory_mb: int = 2048, cpu_seconds: int = 300):
        self.workspace, self.venv = Path(workspace), venv
        self.memory_mb, self.cpu_seconds = memory_mb, cpu_seconds
        self.home = Path(tempfile.mkdtemp(prefix="shopdev-home-"))   # not your real HOME (~/.ssh, ~/.bashrc)

    def _env(self) -> dict:
        # why: a scrubbed env keeps API keys out of reach of anything the agent runs (TEXTBOOK §4)
        env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
        env["HOME"] = str(self.home)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if self.venv:
            env["PATH"] = f"{Path(self.venv) / 'bin'}:{env.get('PATH', '/usr/bin:/bin')}"
        return env

    def run(self, command: str, timeout_s: int = 120) -> ShellResult:
        t0 = time.perf_counter()
        # why ulimit in the shell rather than preexec_fn: preexec_fn is unsafe in threaded programs (our tracer
        # has threads), and a failing limit (e.g. -v on macOS) must not break every command
        limits = f"ulimit -v {self.memory_mb * 1024} 2>/dev/null; ulimit -t {self.cpu_seconds} 2>/dev/null; "
        proc = subprocess.Popen(["bash", "-c", limits + command], cwd=self.workspace, env=self._env(), text=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
        try:
            out, err = proc.communicate(timeout=timeout_s)
            return ShellResult(proc.returncode, out, err, False, time.perf_counter() - t0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)       # the whole group, not just bash
            except ProcessLookupError:
                pass
            try:
                out, err = proc.communicate(timeout=5)   # a daemonized grandchild could hold the pipes open
            except subprocess.TimeoutExpired:
                out, err = "", ""
            return ShellResult(None, out or "", err or "", True, time.perf_counter() - t0)


class DockerSandbox:
    def __init__(self, workspace: Path, image: str = "agentic-course/shopdev:latest", memory: str = "1g",
                 cpus: str = "1", pids: int = 256, network: bool = False):
        self.workspace, self.image = Path(workspace).resolve(), image
        self.memory, self.cpus, self.pids, self.network = memory, cpus, pids, network

    def command_line(self, command: str) -> list[str]:
        # --pull never: never fetch an image by this name from a registry (anyone could publish one)
        argv = ["docker", "run", "--rm", "--pull", "never"]
        if not self.network:
            argv += ["--network", "none"]          # the single most important flag: no exfiltration channel
        argv += ["--memory", self.memory, "--cpus", self.cpus, "--pids-limit", str(self.pids),
                 "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                 "--user", f"{os.getuid()}:{os.getgid()}",
                 "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1",
                 "-v", f"{self.workspace}:/work", "-w", "/work", self.image, "bash", "-c", command]
        return argv

    def run(self, command: str, timeout_s: int = 120) -> ShellResult:
        name = f"shopdev-{uuid.uuid4().hex[:10]}"
        argv = self.command_line(command)
        argv[3:3] = ["--name", name]
        t0 = time.perf_counter()
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s, stdin=subprocess.DEVNULL)
            return ShellResult(r.returncode, r.stdout, r.stderr, False, time.perf_counter() - t0)
        except subprocess.TimeoutExpired as e:
            subprocess.run(["docker", "kill", name], capture_output=True)
            return ShellResult(None, (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""),
                               "", True, time.perf_counter() - t0)


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=5).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def image_available(image: str = "agentic-course/shopdev:latest") -> bool:
    return subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0


def make_sandbox(workspace: Path, prefer: str = "docker", venv: Path | None = None):
    if prefer == "docker" and docker_available() and image_available():
        return DockerSandbox(workspace)
    if prefer == "docker":
        print("! Docker or the shopdev image is not available: using LocalSandbox "
              "(process limits only; NOT a security boundary).")
    return LocalSandbox(workspace, venv=venv)
