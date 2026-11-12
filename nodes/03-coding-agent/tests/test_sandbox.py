"""Sandboxes: the local one runs for real; Docker's argv is checked offline (and run only with -m docker)."""
import os

import pytest

from agentlab.shopdev.sandbox import DockerSandbox, LocalSandbox, ShellResult, format_shell_result, truncate_output


def test_truncate_keeps_head_and_tail():
    text = "H" * 7000 + "M" * 20000 + "T" * 5000
    out = truncate_output(text, limit=10_000)
    assert out.startswith("H" * 6000) and out.endswith("T" * 4000) and "chars omitted" in out
    assert truncate_output("short") == "short"


def test_format():
    s = format_shell_result(ShellResult(1, "out", "", False, 0.5))
    assert s.startswith("exit code: 1") and "--- stdout ---\nout" in s and "stderr" not in s
    assert "TIMED OUT" in format_shell_result(ShellResult(None, "", "", True, 30.0))


def test_local_runs_in_workspace_with_scrubbed_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    (tmp_path / "f.txt").write_text("hello")
    r = LocalSandbox(tmp_path).run("cat f.txt; echo; pwd; echo KEY=${ANTHROPIC_API_KEY:-none}")
    assert r.exit_code == 0 and "hello" in r.stdout and str(tmp_path) in r.stdout
    assert "KEY=none" in r.stdout, "secrets must not be in the sandbox environment"


def test_local_home_is_not_yours_and_stdin_is_closed(tmp_path):
    r = LocalSandbox(tmp_path).run("echo $HOME; cat; echo after-cat", timeout_s=5)
    assert os.path.expanduser("~") not in r.stdout.splitlines()[0], "~/.ssh, ~/.bashrc must be out of reach"
    assert "after-cat" in r.stdout and not r.timed_out, "stdin is /dev/null, so a bare `cat` returns at once"


def test_local_timeout_kills(tmp_path):
    r = LocalSandbox(tmp_path).run("sleep 5; echo never", timeout_s=1)
    assert r.timed_out and r.exit_code is None and "never" not in r.stdout and r.duration_s < 4


def test_local_venv_on_path(tmp_path):
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    r = LocalSandbox(tmp_path, venv=venv).run("echo $PATH")
    assert r.stdout.startswith(str(venv / "bin"))


def test_docker_argv_has_the_isolation_flags(tmp_path):
    argv = DockerSandbox(tmp_path).command_line("pytest -q")
    joined = " ".join(argv)
    for flag in ("--rm", "--pull never", "--network none", "--cap-drop ALL", "--security-opt no-new-privileges", "--pids-limit 256",
                 "--memory 1g", f"-v {tmp_path}:/work", "-w /work"):
        assert flag in joined, flag
    assert argv[-3:] == ["bash", "-c", "pytest -q"]
    assert "--user" in argv and argv[argv.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    env_values = [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]
    assert all(not v.startswith(("ANTHROPIC", "OPENROUTER", "OPENAI")) for v in env_values)
    assert "--network" not in DockerSandbox(tmp_path, network=True).command_line("x")


@pytest.mark.docker
def test_docker_has_no_network(tmp_path):
    r = DockerSandbox(tmp_path).run("python -c \"import urllib.request; urllib.request.urlopen('https://example.com', timeout=3)\"")
    assert r.exit_code != 0
