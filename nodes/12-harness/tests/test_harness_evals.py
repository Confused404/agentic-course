import pytest

from agentlab.harness.evals import render, summarize, to_trial
from agentlab.harness.loops import HarnessResult


def _acc(n_ok):
    return {f: {"passed": i < n_ok, "failed": 0 if i < n_ok else 2, "total": 3}
            for i, f in enumerate(["F1", "F2", "F3", "F4", "F5"])}


def test_to_trial_overclaims_and_tamper():
    r = HarnessResult("loop", stop="done", features=[{"id": f, "status": "passing"} for f in ["F1", "F2", "F3"]])
    t = to_trial("loop@fast", r, _acc(1), True)
    assert t.extra["accepted"] == 1 and t.extra["overclaims"] == ["F2", "F3"] and t.verdict == "fail"
    good = to_trial("full@fast", HarnessResult("full", stop="done"), _acc(5), True)
    assert good.verdict == "pass"
    tampered = to_trial("x", HarnessResult("x", tamper=["tests/test_engine.py"]), _acc(5), True)
    assert tampered.verdict == "fail", "all features accepted, but it edited the tests"


def test_summary_and_render():
    ts = [to_trial("loop@fast", HarnessResult("loop", features=[{"id": "F1", "status": "passing"}]), _acc(0), True),
          to_trial("full@fast", HarnessResult("full"), _acc(5), True)]
    s = summarize(ts)
    assert s["loop@fast"]["overclaims"] == 1 and s["full@fast"]["all_accepted"] == 1
    md = render(ts)
    assert "| full@fast | 5.0/5 | 1/1 |" in md and "F1 1/1" in md


def test_cli(tmp_path, monkeypatch, capsys):
    import agentlab.harness.__main__ as cli
    monkeypatch.setattr(cli, "RUNS", tmp_path)
    for bad in (["run", "--configs", "nope"], ["run", "--models", "nosuchalias"]):
        with pytest.raises(ValueError):
            cli.main(bad)
    assert not (tmp_path / "harness").exists()
    assert cli.main(["new", str(tmp_path / "w")]) == 0
    assert cli.main(["accept", str(tmp_path / "w")]) == 0
    assert "0/5 features accepted" in capsys.readouterr().out
