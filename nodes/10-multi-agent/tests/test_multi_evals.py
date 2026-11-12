import json

import pytest

from agentlab.costs import Budget, BudgetExceeded
from agentlab.llm import fake
from agentlab.multi.architectures import MultiResult, CallRecord
from agentlab.multi.evals import render, run_multi, summarize, to_trial
from agentlab.multi.tasks import TASKS, gold_top_units

TOP = next(t for t in TASKS if t.id == "top_units_90d")


def test_to_trial(conn):
    r = MultiResult("orch:a:b", gold_top_units(conn), 0.01, 2.0,
                    [CallRecord("lead", 500, 50), CallRecord("worker:bags#1", 300, 20)], agents=2)
    t = to_trial(TOP, r, conn)
    assert t.verdict == "pass" and t.extra["peak_context"] == 500 and t.extra["input_tokens"] == 800
    assert t.extra["tokens_by_role"] == {"lead": 550, "worker": 320}
    assert to_trial(TOP, MultiResult("x", None, error="no answer"), conn).verdict == "error"
    assert to_trial(TOP, MultiResult("x", ["nope"]), conn).verdict == "fail"
    lucky = to_trial(TOP, MultiResult("orch:a:b", gold_top_units(conn), missing_shards=["bags"]), conn)
    assert lucky.verdict == "fail" and "missing" in lucky.grades[0].detail, "right by luck, with a shard missing"
    limited = to_trial(TOP, MultiResult("orch:a:b", None, error="x", provider_errors=2), conn)
    assert limited.verdict == "error" and limited.error_kind == "provider"


def test_run_summarize_render(conn, tmp_path):
    gold = gold_top_units(conn)
    scripts = {"good": lambda: fake.ScriptedModel([fake.call("submit_answer", answer=gold), fake.say("ok")]),
               "bad": lambda: fake.ScriptedModel([fake.say("dunno")])}
    trials = run_multi([TOP], ["single:good", "single:bad"], lambda a: scripts[a](), conn, out_dir=tmp_path)
    assert [t.verdict for t in trials] == ["pass", "error"]
    assert len((tmp_path / "trials.jsonl").read_text().splitlines()) == 2
    tr = json.loads((tmp_path / "transcripts" / "top_units_90d__single_good__0.json").read_text())
    assert "single" in tr
    s = summarize(trials)
    assert s["single:good"]["accuracy"] == 1.0 and s["single:bad"]["errors"] == 1
    assert s["single:good"]["by_task"] == {"top_units_90d": "1/1"}
    md = render(trials, "single:good")
    assert "| single:good |" in md and "1.0×" in md and "| top_units_90d |" in md


def test_budget_exhaustion_stops_the_run(conn):
    b = Budget(limit_usd=0.0)
    b.spent_usd = 0.5
    with pytest.raises(BudgetExceeded):
        run_multi([TOP], ["single:x"], lambda a: fake.ScriptedModel([fake.say("x")]), conn, budget=b)


def test_cli_fails_fast(tmp_path, monkeypatch):
    import agentlab.multi.__main__ as cli
    monkeypatch.setattr(cli, "RUNS", tmp_path)
    for bad in ["single", "orch:mid", "single:nosuchalias"]:
        with pytest.raises(ValueError):
            cli.main(["run", "--archs", bad])
    assert not (tmp_path / "multi").exists()
