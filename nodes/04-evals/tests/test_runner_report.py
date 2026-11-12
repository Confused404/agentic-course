"""Runner (isolation, verdicts, persistence) and report (uses YOUR stats.py, so it's red until stats is done)."""
import json

import pytest

from agentlab.costs import Budget, BudgetExceeded
from agentlab.evals.report import compare, pareto, per_task, render_markdown, summarize
from agentlab.evals.runner import Trial, load_trials, run_eval, run_trial
from agentlab.evals.task import Task
from agentlab.llm.fake import ScriptedModel, call, fail, say
from agentlab.llm.types import Usage

REFUND = Task("refund", 9001, [{"type": "refund", "order_id": 4822, "status": "issued"}], turns=["refund 4822"])


def good():
    return ScriptedModel([call("issue_refund", order_id=4822, amount_cents=4899, reason="changed_mind"), say("done")])


def liar():
    return ScriptedModel([say("done!")])


def test_trial_verdicts(template_db):
    assert run_trial(REFUND, good(), template_db=template_db).verdict == "pass"
    t = run_trial(REFUND, liar(), template_db=template_db, model_label="liar", trial=2)
    assert t.verdict == "fail" and t.model == "liar" and t.trial == 2 and t.replies == ["done!"]
    err = run_trial(REFUND, ScriptedModel([fail(RuntimeError("503"))]), template_db=template_db)
    assert err.verdict == "error" and "503" in err.error
    unk = Task("u", 9001, [{"type": "judge", "rubric": "r"}], turns=["hi"])
    assert run_trial(unk, ScriptedModel([say("hi")]), template_db=template_db).verdict == "unknown"


def test_provider_errors_are_not_model_failures(template_db):
    class RateLimitError(Exception):
        pass
    t = run_trial(REFUND, ScriptedModel([fail(RateLimitError("429"))]), template_db=template_db)
    assert t.verdict == "error" and t.error_kind == "provider"
    t2 = run_trial(REFUND, ScriptedModel([fail(ValueError("bug"))]), template_db=template_db)
    assert t2.error_kind == "agent"
    s = summarize([t, t2, run_trial(REFUND, good(), template_db=template_db)])
    m = next(iter(s.values()))
    assert m["pass_rate"] == pytest.approx(0.5), "provider error excluded; agent error counts as a failure"
    assert m["provider_errors"] == 1 and m["pass_rate_conservative"] == pytest.approx(1 / 3)


def test_judge_spend_counts_against_the_budget(template_db):
    class PricyJudge:
        provider, model = "fake", "judge"

        def complete(self, **kw):
            r = say('{"reasoning": "x", "verdict": "pass"}')
            r.usage = Usage(input_tokens=10_000_000)
            return r
    task = Task("j", 9001, [{"type": "judge", "rubric": "r"}], turns=["hi"])
    with pytest.raises(BudgetExceeded):
        run_trial(task, ScriptedModel([say("hi")]), template_db=template_db, budget=Budget(limit_usd=1),
                  judge_factory=PricyJudge)


def test_budget_exceeded_propagates(template_db):
    m = good()
    m.script[0].usage = Usage(input_tokens=10_000_000)
    with pytest.raises(BudgetExceeded):
        run_trial(REFUND, m, template_db=template_db, budget=Budget(limit_usd=0.5))


def test_assistant_opts_reach_the_assistant(template_db):
    m = ScriptedModel([say("hi")])
    run_trial(REFUND, m, template_db=template_db, assistant_opts={"system_prompt": "CUSTOM PROMPT {today}"})
    assert m.calls[0]["system"].startswith("CUSTOM PROMPT 2026-11-01")


def test_run_eval_isolated_interleaved_and_saved(template_db, tmp_path):
    out = tmp_path / "run"
    trials = run_eval([REFUND], {"good": good, "liar": liar}, template_db=template_db, trials=3, out_dir=out)
    assert [(t.model, t.trial) for t in trials] == [("good", 0), ("liar", 0), ("good", 1), ("liar", 1), ("good", 2), ("liar", 2)]
    assert [t.verdict for t in trials if t.model == "good"] == ["pass"] * 3, "fresh DB each trial (one refund per order)"
    meta = json.loads((out / "meta.json").read_text())
    assert meta["models"] == ["good", "liar"] and meta["trials"] == 3
    back = load_trials(out / "trials.jsonl")
    assert len(back) == 6 and back[0].grades[0].verdict == "pass" and isinstance(back[0], Trial)


def T(model, task, verdict, cost=0.01, tags=("a",)):
    return Trial(task, 0, model, verdict, [], [], [], [], cost, 1.0, 1, ["end_turn"], None, list(tags), "dev")


def trials_fixture():
    ts = []
    for i in range(10):
        ts += [T("A", f"t{i}", "pass" if i < 7 else "fail") for _ in range(3)]
        ts += [T("B", f"t{i}", "pass", cost=0.05) for _ in range(3)]
    ts.append(T("A", "t0", "unknown"))
    ts.append(T("B", "t9", "error"))
    return ts


def test_summary_numbers():
    s = summarize(trials_fixture(), k=3)
    a, b = s["A"], s["B"]
    assert a["passes"] == 21 and a["unknown"] == 1 and a["pass_rate"] == pytest.approx(21 / 30)
    assert a["wilson"][0] < 0.7 < a["wilson"][1]
    assert a["task_mean"] == pytest.approx(0.7) and a["task_ci"][0] <= 0.7 <= a["task_ci"][1]
    assert a["pass_hat_k"] == pytest.approx(0.7) and a["pass_at_k"] == pytest.approx(0.7)
    assert b["errors"] == 1 and b["pass_rate"] == pytest.approx(30 / 31)
    assert b["cost_per_pass"] == pytest.approx(b["cost_per_trial"] * 31 / 30)
    assert a["by_tag"]["a"] == pytest.approx(21 / 30)
    assert per_task(trials_fixture())["A"]["t0"] == (3, 3), "unknown excluded from graded trials"


def test_compare_pareto_and_markdown():
    ts = trials_fixture()
    d = compare(ts, "A", "B")
    assert d["tasks"] == 10 and d["diff"] > 0 and d["lo"] >= 0
    s = summarize(ts)
    assert set(pareto(s)) == {"A", "B"}, "A is cheaper, B is better: neither dominates"
    s["C"] = dict(s["A"], task_mean=0.5, cost_per_trial=1.0)
    assert "C" not in pareto(s)
    md = render_markdown(ts, title="T")
    assert md.startswith("# T") and "Pareto" in md and "Failures to read" in md and "t7" in md
    with pytest.raises(ValueError, match="not in these trials"):
        compare(ts, "A", "Z")
    ts[0].latency_s = None
    assert "| A |" in render_markdown([t for t in ts if t.model == "A" and t.latency_s is None] + ts[1:], "x")
