
import pytest

from agentlab.harness import project
from agentlab.harness.hooks import HookedExecutor, protect_in_shell, syntax_check
from agentlab.harness.session import ProjectGate, load_skills, run_session, skill_tool, skills_index
from agentlab.llm.types import ToolResultBlock, ToolUseBlock


def test_workspace_checkpoints_and_reset(ws):
    start = project.head(ws)
    assert project.read_features(ws)[0]["id"] == "F1"
    (ws / "promo" / "new.py").write_text("x = 1\n")
    assert project.changed_files(ws, start) == ["promo/new.py"]
    c = project.checkpoint(ws, "add new")
    assert c and project.checkpoint(ws, "nothing") is None
    (ws / "junk.txt").write_text("junk")
    project.reset_to(ws, start)
    assert not (ws / "promo" / "new.py").exists() and not (ws / "junk.txt").exists()
    with pytest.raises(FileExistsError):
        project.new_workspace(ws)


def test_acceptance_is_outside_and_fails_on_the_template(ws):
    assert not any("acceptance" in p.relative_to(ws).as_posix() for p in ws.rglob("*"))
    acc = project.run_acceptance(ws)
    assert list(acc) == list(project.FEATURES) and not any(v["passed"] for v in acc.values())
    assert all(v["total"] > 0 for v in acc.values())
    assert project.run_visible_tests(ws)[0], "the template's own tests pass"


def test_project_gate(ws):
    g = ProjectGate(ws, {"tests/test_engine.py"})
    d = lambda tool, **a: g.decide(tool, a).action  # noqa: E731
    assert d("write_file", path="tests/test_f1.py", content="") == "allow", "writing NEW tests is the job"
    assert d("edit_file", path="tests/test_engine.py", old_str="a", new_str="b") == "deny"
    assert d("edit_file", path="features.json", old_str="a", new_str="b") == "deny"
    assert ProjectGate(ws, set(), progress_writable=True).decide(
        "edit_file", {"path": "features.json", "old_str": "a", "new_str": "b"}).action == "allow"
    for p in ("BACKLOG.md", "AGENTS.md", "conftest.py", "skills/promo-testing/SKILL.md"):
        assert d("write_file", path=p, content="") == "deny", p
    assert d("run_shell", command="python -m promo explain cart.json") == "allow"
    assert d("run_shell", command="python -m pytest -q") == "allow"
    assert d("run_shell", command="python -c 'print(1)'") != "allow"


def test_hooks(ws):
    class Inner:
        def specs(self):
            return []

        def execute(self, call):
            return ToolResultBlock(call.id, "ok")
    pre = protect_in_shell(["tests/test_engine.py", "features.json"])
    h = HookedExecutor(Inner(), pre=[pre], post=[syntax_check(ws)])
    r = h.execute(ToolUseBlock("1", "run_shell", {"command": "sed -i 's/1/2/' tests/test_engine.py"}))
    assert r.is_error and "protected" in r.text and h.events
    assert not h.execute(ToolUseBlock("2", "run_shell", {"command": "cat tests/test_engine.py"})).is_error
    (ws / "promo" / "bad.py").write_text("def f(:\n")
    r = h.execute(ToolUseBlock("3", "write_file", {"path": "promo/bad.py", "content": "def f(:\n"}))
    assert "[hook]" in r.text and "compile" in r.text


def test_skills(ws):
    skills = load_skills(ws / "skills")
    assert [s.name for s in skills] == ["promo-testing"] and "Thresholds" in skills[0].body
    assert "promo-testing:" in skills_index(skills)
    t = skill_tool(skills)
    assert "Thresholds" in t.fn(name="promo-testing")


def test_session_with_skills_and_stop_hook(ws, worker):
    def plan(w, task, turn, messages):
        last = messages[-1].text if messages[-1].role == "user" else ""
        if turn == 1:
            return [("load_skill", {"name": "promo-testing"}),
                    ("write_file", {"path": "tests/test_f1.py", "content": "def test_x():\n    assert 1 == 2\n"})]
        if "[stop hook]" in last:
            return [("edit_file", {"path": "tests/test_f1.py", "old_str": "1 == 2", "new_str": "1 == 1"})]
        return "done"
    m = worker(ws, plan)
    s = run_session(m, ws, "Work on feature F1", hooks=True, skills=True, stop_hook=True, max_turns=6)
    assert "load_skill" in m.seen[0]["tools"] and "promo-testing" in m.seen[0]["system"]
    assert s.continuations == 1 and any("stop hook" in e for e in s.events)
    assert project.run_visible_tests(ws)[0]


def test_a_fake_pytest_in_the_workspace_fools_nothing(ws):
    (ws / "pytest.py").write_text("print('99 passed')\nraise SystemExit(0)\n")
    acc = project.run_acceptance(ws)
    assert not any(v["passed"] for v in acc.values()), "the hidden tests must run the real pytest"
    start = project.head(ws)
    assert project.suspicious_files(ws, "HEAD") == ["pytest.py"] and start


def test_continuations_share_the_turn_budget(ws, worker):
    def plan(w, task, turn, messages):
        if turn == 1:
            return [("write_file", {"path": "tests/test_f1.py", "content": "def test_x():\n    assert False\n"})]
        return [("read_file", {"path": "AGENTS.md"})] if turn % 2 else "done"
    s = run_session(worker(ws, plan), ws, "Work on feature F1", stop_hook=True, max_turns=6, max_continuations=5)
    assert s.turns <= 6, "a hooked session gets no more turns than an unhooked one"


def test_tests_from_earlier_sessions_stay_editable(ws, worker):
    (ws / "tests" / "test_f1.py").write_text("def test_a():\n    assert True\n")
    def plan(w, task, turn, messages):
        if turn == 1:
            return [("edit_file", {"path": "tests/test_f1.py", "old_str": "assert True", "new_str": "assert 1"})]
        return "done"
    s = run_session(worker(ws, plan), ws, "F2", protected_tests={"tests/test_engine.py"}, max_turns=3)
    assert "assert 1" in (ws / "tests" / "test_f1.py").read_text() and not any("denied" in e for e in s.events)


def test_skill_loads_are_recorded(ws, worker):
    def plan(w, task, turn, messages):
        return [("load_skill", {"name": "promo-testing"})] if turn == 1 else "done"
    s = run_session(worker(ws, plan), ws, "F1", skills=True, max_turns=3)
    assert "skill loaded: promo-testing" in s.events


def test_gate_is_case_insensitive(ws):
    g = ProjectGate(ws, {"tests/test_engine.py"})
    assert g.decide("write_file", {"path": "backlog.md", "content": ""}).action == "deny"
    assert g.decide("edit_file", {"path": "Tests/Test_Engine.py", "old_str": "a", "new_str": "b"}).action == "deny"
