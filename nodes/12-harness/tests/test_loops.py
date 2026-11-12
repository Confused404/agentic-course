import json

from agentlab.harness import project
from agentlab.harness.evaluator import Verdict, feature_spec
from agentlab.harness.loops import CONFIGS, run_harness


def _run(ws, worker, plan, name, **kw):
    m = worker(ws, plan)
    return run_harness(CONFIGS[name], lambda role: m, ws, **kw), m


def test_feature_spec(ws):
    assert feature_spec(ws, "F3").startswith("## F3: Stacking rules") and "## F4" not in feature_spec(ws, "F3")


def test_self_reporting_loop_believes_a_liar(ws, worker, plans, naive_progress):
    r, m = _run(ws, worker, plans["liar"], "loop", max_sessions=10)
    assert r.stop == "done" and r.sessions == 5
    assert all(f["status"] == "passing" for f in r.features), "every feature 'passing', nothing implemented"
    assert "fresh" not in m.seen[0]["last"] and m.sessions == 5, "one fresh session per feature"


def test_verified_loop_doesnt(ws, worker, plans, naive_progress):
    r, _ = _run(ws, worker, plans["liar"], "loop+verify", max_sessions=4)
    assert not any(f["status"] == "passing" for f in r.features)
    f1 = r.features[0]
    assert f1["status"] == "failing" and "test_f1.py" in f1["notes"]


def test_verified_loop_believes_agent_written_tests(ws, worker, plans, naive_progress):
    """Green tests the agent wrote itself are weak evidence: the harness marks everything passing, the hidden
    acceptance tests (run in evals) will disagree."""
    r, _ = _run(ws, worker, plans["box_ticker"], "loop+verify", max_sessions=10)
    assert r.stop == "done" and all(f["status"] == "passing" for f in r.features)
    assert not any(v["passed"] for v in project.run_acceptance(ws).values())


def test_failed_attempts_are_reverted_and_noted(ws, worker, naive_progress):
    def broken(w, task, turn, messages):
        if turn == 1:
            return [("write_file", {"path": "tests/test_f1.py", "content": "def test_x():\n    assert False\n"}),
                    ("write_file", {"path": "promo/half_done.py", "content": "x = 1\n"})]
        return "done"
    r, _ = _run(ws, worker, broken, "loop+verify", max_sessions=1)
    assert not (ws / "promo" / "half_done.py").exists(), "a failed attempt leaves no half-done code"
    assert r.features[0]["status"] == "failing" and "harness check failed" in r.features[0]["notes"]


def test_evaluator_can_veto(ws, worker, plans, naive_progress, monkeypatch):
    from agentlab.harness import loops
    monkeypatch.setattr(loops, "evaluate", lambda model, ws_, fid, diff, budget=None: Verdict(
        False, [f"{fid}: min_spend boundary untested"]))
    r, _ = _run(ws, worker, plans["box_ticker"], "full", max_sessions=2)
    assert r.evaluator_rejections == 2 and r.features[0]["status"] == "failing"
    assert "evaluator" in r.features[0]["notes"] and "min_spend" in r.features[0]["notes"]


def test_single_session_and_progress_validation(ws, worker, plans, naive_progress):
    def renamer(w, task, turn, messages):
        if turn == 1:
            feats = json.loads((w / "features.json").read_text())
            old = (w / "features.json").read_text()
            feats.pop()
            return [("edit_file", {"path": "features.json", "old_str": old, "new_str": json.dumps(feats)})]
        return "done"
    r, m = _run(ws, worker, renamer, "single")
    assert r.stop == "single" and m.sessions == 1
    assert any("progress edit rejected" in e for e in r.events)
    assert len(project.read_features(ws)) == 5, "the harness put its version back"


def test_tamper_detection(ws):
    from agentlab.harness.loops import _protected_changes
    start = project.head(ws)
    (ws / "tests" / "test_engine.py").write_text("# gone\n")
    (ws / "BACKLOG.md").write_text("# easier now\n")
    (ws / "features.json").write_text("[]")
    assert _protected_changes(ws, start, {"tests/test_engine.py"}) == ["BACKLOG.md", "tests/test_engine.py"]
    (ws / "sitecustomize.py").write_text("x = 1\n")
    (ws / "tests" / "test_peek.py").write_text("from agentlab.harness.project import ACCEPTANCE\n")
    got = _protected_changes(ws, start, {"tests/test_engine.py"})
    assert "sitecustomize.py" in got and any("references the harness" in g for g in got)


def test_evaluator_contract(ws, worker):
    from agentlab.harness.evaluator import evaluate

    def says(*steps):
        def plan(w, task, turn, messages):
            return steps[turn - 1] if turn <= len(steps) else "done"
        return worker(ws, plan)
    m = says([("verdict", {"passed": True, "issues": []})], [("verdict", {"passed": False})], "ok")
    v = evaluate(m, ws, "F1", "diff")
    assert v.passed, "the first verdict counts"
    assert m.seen[0]["tools"] == ["grep", "list_dir", "read_file", "run_tests", "verdict"], "no write tools"
    assert not evaluate(says("looks fine to me"), ws, "F1", "diff").passed, "no verdict fails closed"
    assert not evaluate(says([("verdict", {"passed": "true"})]), ws, "F1", "diff").passed, "a string isn't a pass"


def test_budget_stop_is_not_a_rejection(ws, worker, plans, naive_progress, monkeypatch):
    from agentlab.costs import Budget
    from agentlab.harness import loops
    b = Budget(limit_usd=1.0)

    def broke(model, ws_, fid, diff, budget=None):
        b.spent_usd = 2.0
        return Verdict(False, ["evaluator gave no verdict (stop=budget)"], out_of_budget=True)
    monkeypatch.setattr(loops, "evaluate", broke)
    m = worker(ws, plans["box_ticker"])
    r = run_harness(CONFIGS["loop+verify+eval"], lambda role: m, ws, budget=b, max_sessions=3)
    assert r.stop == "budget" and r.evaluator_rejections == 0
    assert (ws / "tests" / "test_f1.py").exists(), "no reset for an attempt the budget cut short"


def test_agent_notes_survive(ws, worker, plans, naive_progress):
    set_status = plans["set_status"]

    def noter(w, task, turn, messages):
        if turn == 1:
            return [set_status(w, "F1", "in_progress", notes="rounding is floor, see spec")]
        return "stuck"
    r, _ = _run(ws, worker, noter, "loop+verify", max_sessions=1)
    n = r.features[0]["notes"]
    assert n.startswith("harness check failed") and "rounding is floor" in n


def test_run_ablation(tmp_path, monkeypatch):
    from agentlab.harness import evals
    from agentlab.harness.loops import HarnessResult

    def fake_run(cfg, factory, ws, **kw):
        if cfg.name == "loop":
            raise ConnectionError("provider down")
        return HarnessResult(cfg.name, stop="done")
    monkeypatch.setattr(evals, "run_harness", fake_run)
    (tmp_path / "trials.jsonl").write_text("stale\n")
    ts = evals.run_ablation(["single", "loop"], ["fast"], lambda a: None, tmp_path)
    assert [t.verdict for t in ts] == ["fail", "error"] and ts[1].error_kind == "provider"
    assert len((tmp_path / "trials.jsonl").read_text().splitlines()) == 2
    assert (tmp_path / "ws-single-fast-0" / ".harness-result.json").exists()
