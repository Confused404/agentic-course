"""AGENT-OFF code under test: your edit_file (agentlab/shopdev/edit.py)."""
import os

import pytest

from agentlab.shopdev.edit import EditError, edit_file
from agentlab.tools.errors import ToolError

SRC = "def f(x):\n    if x > 1:\n        return x * 2\n    return x\n\n\ndef g(x):\n    return x * 2\n"


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "m.py").write_text(SRC)
    return tmp_path


def read(ws):
    return (ws / "pkg" / "m.py").read_text()


def test_unique_replace_and_snippet(ws):
    out = edit_file(ws, "pkg/m.py", "        return x * 2\n", "        return x * 3\n")
    assert read(ws) == SRC.replace("        return x * 2\n", "        return x * 3\n")
    first, *snippet = out.splitlines()
    assert first == "Edited pkg/m.py: replaced 1 occurrence(s)."
    assert "     3\t        return x * 3" in snippet, "line-numbered snippet of the new text"
    assert snippet[0].lstrip().startswith("1\t"), "snippet starts 3 lines before (clamped to line 1)"


def test_ambiguous_match_reports_lines(ws):
    with pytest.raises(EditError) as e:
        edit_file(ws, "pkg/m.py", "return x * 2", "return x")
    msg = str(e.value)
    assert "2" in msg and "3" in msg and "8" in msg, "count and both line numbers"
    assert "replace_all" in msg
    assert read(ws) == SRC, "no partial writes"


def test_replace_all(ws):
    out = edit_file(ws, "pkg/m.py", "x * 2", "x * 4", replace_all=True)
    assert "replaced 2 occurrence(s)" in out and read(ws).count("x * 4") == 2


def test_not_found_with_whitespace_hint(ws):
    with pytest.raises(EditError) as e:
        edit_file(ws, "pkg/m.py", "if x > 1:\n  return x * 2", "if x > 1:\n  return 0")   # wrong indentation
    msg = str(e.value).lower()
    assert "not found" in msg and "whitespace" in msg and "line 2" in msg


def test_not_found_plain(ws):
    with pytest.raises(EditError) as e:
        edit_file(ws, "pkg/m.py", "def nope()", "x")
    assert "not found" in str(e.value).lower() and "whitespace" not in str(e.value).lower()


@pytest.mark.parametrize("path", ["../outside.py", "/etc/hosts", "pkg/../../x.py"])
def test_outside_workspace(ws, path):
    with pytest.raises(EditError) as e:
        edit_file(ws, path, "a", "b")
    assert "outside" in str(e.value).lower()


def test_symlink_escape(ws, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere") / "secret.py"
    outside.write_text("TOKEN = 1\n")
    os.symlink(outside, ws / "link.py")
    with pytest.raises(EditError):
        edit_file(ws, "link.py", "TOKEN = 1", "TOKEN = 2")
    assert outside.read_text() == "TOKEN = 1\n"


def test_missing_file_empty_and_noop(ws):
    with pytest.raises(EditError) as e:
        edit_file(ws, "pkg/new.py", "a", "b")
    assert "write_file" in str(e.value)
    with pytest.raises(EditError):
        edit_file(ws, "pkg/m.py", "", "b")
    with pytest.raises(EditError):
        edit_file(ws, "pkg/m.py", "return x\n", "return x\n")


def test_preserves_crlf_mode_and_is_a_tool_error(ws):
    p = ws / "w.txt"
    p.write_bytes(b"a\r\nb\r\nc\r\n")
    os.chmod(p, 0o755)
    edit_file(ws, "w.txt", "b", "B")
    assert p.read_bytes() == b"a\r\nB\r\nc\r\n"
    assert (p.stat().st_mode & 0o777) == 0o755, "atomic replace must keep permission bits"
    assert issubclass(EditError, ToolError), "so the registry reports it to the model cleanly"
