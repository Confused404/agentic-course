"""Workspace-scoped file tools (coding agent builds these)."""
import pytest

from agentlab.shopdev.fs_tools import grep, list_dir, read_file, write_file
from agentlab.tools.errors import ToolError


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "m.py").write_text("".join(f"line {i}\n" for i in range(1, 501)))
    (tmp_path / "a" / "n.txt").write_text("alpha\nBeta\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("line 9999\n")
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01line 1")
    (tmp_path / "empty.py").write_text("")
    return tmp_path


def test_read_numbering_and_paging(ws):
    out = read_file(ws, "a/m.py", offset=10, limit=3).splitlines()
    assert out[0] == "    10\tline 10" and out[2] == "    12\tline 12"
    assert out[-1] == "[showing lines 10-12 of 500; use offset/limit to see more]"
    full = read_file(ws, "a/n.txt").splitlines()
    assert full == ["     1\talpha", "     2\tBeta"], "no footer when everything is shown"
    assert read_file(ws, "empty.py") == "[empty file]"


def test_read_errors(ws):
    for bad in ("nope.py", "a", "bin.dat", "../x"):
        with pytest.raises(ToolError):
            read_file(ws, bad)


def test_list_dir(ws):
    out = list_dir(ws).splitlines()
    assert out == ["a/", "bin.dat", "empty.py"], ".git is ignored, dirs have /"
    for i in range(5):
        (ws / "a" / f"f{i}.txt").write_text("x")
    assert list_dir(ws, "a", max_entries=3).splitlines()[-1] == "[4 more entries]"


def test_grep(ws):
    out = grep(ws, r"line 1\d\d$", path="a", max_results=50)          # 100 matches, capped at 50
    lines = out.splitlines()
    assert lines[0] == "a/m.py:100: line 100" and len(lines) == 50 + 1 and lines[-1].startswith("[results truncated")
    assert grep(ws, "beta") == "No matches."
    assert grep(ws, "(?i)beta", glob="*.txt") == "a/n.txt:2: Beta"
    assert "9999" not in grep(ws, "9999"), ".git ignored"
    with pytest.raises(ToolError):
        grep(ws, "([unclosed")


def test_grep_never_reads_secret_files(ws):
    (ws / ".env").write_text("ANTHROPIC_API_KEY=sk-secret\n")
    (ws / "a" / "server.pem").write_text("KEY material\n")
    assert grep(ws, "KEY") == "No matches.", "a recursive grep must not become a way to read .env"
    assert grep(ws, "KEY", glob=".env") == "No matches."


def test_write_file(ws):
    assert write_file(ws, "new/pkg/x.py", "a\nb\n") == "Created new/pkg/x.py (2 lines)."
    assert (ws / "new/pkg/x.py").read_text() == "a\nb\n"
    with pytest.raises(ToolError) as e:
        write_file(ws, "a/n.txt", "overwrite")
    assert "edit_file" in str(e.value)
    with pytest.raises(ToolError):
        write_file(ws, "../escape.py", "x")
