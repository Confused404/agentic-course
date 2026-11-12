"""shopdev end to end with a scripted model on a tiny buggy project. Uses YOUR edit_file and PermissionGate
(so these stay red until you've written them) and the real LocalSandbox (runs pytest for real)."""
import sys
from pathlib import Path

import pytest

from agentlab.llm.fake import ScriptedModel, call, last_tool_results, say
from agentlab.shopdev.agent import make_dev_tools, run_shopdev
from agentlab.shopdev.sandbox import LocalSandbox

VENV = Path(sys.executable).parent.parent


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text("from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-secret\n")
    return tmp_path


def test_tools_registered(ws):
    reg = make_dev_tools(ws, LocalSandbox(ws, venv=VENV))
    assert reg.names() == ["edit_file", "grep", "list_dir", "read_file", "run_shell", "write_file"]
    for s in reg.specs():
        assert s.input_schema.get("additionalProperties") is False


def test_fix_a_bug_end_to_end(ws):
    def check_tests_pass(system, messages, tools, opts):
        out = last_tool_results(messages)[0].text
        assert "exit code: 0" in out, out
        return say("Root cause: add() subtracted. Fixed; tests pass.")
    model = ScriptedModel([
        call("run_shell", command="python -m pytest -q -p no:cacheprovider tests"),
        call("read_file", path="calc.py"),
        call("edit_file", path="calc.py", old_str="return a - b", new_str="return a + b"),
        call("run_shell", command="python -m pytest -q -p no:cacheprovider tests"),
        check_tests_pass,
    ])
    result, log = run_shopdev("make tests/test_calc.py pass", model, ws, sandbox=LocalSandbox(ws, venv=VENV),
                              approver=lambda *a: pytest.fail("nothing here should need approval"))
    assert result.stop == "end_turn" and "return a + b" in (ws / "calc.py").read_text()
    assert [e.action for e in log] == ["allow"] * 4
    first_run = result.messages[2].content[0].text
    assert "exit code: 1" in first_run, "it reproduced the failure first"


def test_gate_blocks_test_edits_secrets_and_asks(ws):
    asked = []
    model = ScriptedModel([
        call("edit_file", path="tests/test_calc.py", old_str="== 5", new_str="== -1"),
        call("read_file", path=".env"),
        call("run_shell", command="python scripts/whatever.py"),
        say("I was blocked; reporting."),
    ])
    result, log = run_shopdev("make tests pass", model, ws, sandbox=LocalSandbox(ws, venv=VENV),
                              approver=lambda tool, args, reason: asked.append(tool) or False)
    assert [e.action for e in log] == ["deny", "deny", "ask"] and asked == ["run_shell"]
    assert "== 5" in (ws / "tests" / "test_calc.py").read_text()
    results = [m.content[0] for m in result.messages if m.role == "user" and m.content and hasattr(m.content[0], "is_error")]
    assert all(r.is_error for r in results)
    assert "sk-secret" not in str([m.to_dict() for m in result.messages])
