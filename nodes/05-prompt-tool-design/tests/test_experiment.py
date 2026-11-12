"""Experiment runner: interleaved baseline/candidate, paired comparison, log rows. Uses your stats.py via report."""
from agentlab.evals.experiment import Variant, append_log, run_experiment
from agentlab.evals.task import Task
from agentlab.llm.fake import ScriptedModel, call, say

T = [Task(f"t{i}", 9001, [{"type": "refund", "order_id": 4822, "status": "issued"}], turns=["refund 4822"], tags=["refund"],
          split="heldout" if i >= 6 else "dev") for i in range(8)]


def factory():
    """Refunds only when the system prompt is the 'good' one, so the candidate wins."""
    def step(system, messages, tools, opts):
        if "GOOD" in system and not any(getattr(b, "type", "") == "tool_result" for m in messages for b in m.content):
            return call("issue_refund", order_id=4822, amount_cents=4899, reason="changed_mind")
        return say("ok")
    return ScriptedModel([step] * 4)


def test_variant_opts():
    v = Variant("x", prompt="v1", tools="v1", model_opts={"effort": "low"})
    o = v.assistant_opts()
    assert "{today}" in o["system_prompt"] and o["tool_variant"] == "v1" and o["model_opts"] == {"effort": "low"}


def test_experiment_better_and_logged(template_db, tmp_path, monkeypatch):
    import agentlab.assistant.prompts as P
    monkeypatch.setitem(P.PROMPTS, "good", "GOOD prompt {today}")
    r = run_experiment(T, factory, Variant("base"), Variant("cand", prompt="good"), template_db=template_db, trials=2,
                       out_dir=tmp_path / "run")
    assert len(r.baseline) == len(r.candidate) == 16
    assert len((tmp_path / "run" / "trials.jsonl").read_text().splitlines()) == 32, "written as it goes"
    assert set(r.by_split) == {"dev", "heldout"} and r.by_split["heldout"]["tasks"] == 2
    assert r.by_split["heldout"]["verdict"] == "insufficient"
    assert all(t.verdict == "fail" for t in r.baseline) and all(t.verdict == "pass" for t in r.candidate)
    assert r.verdict == "better" and r.comparison["diff"] == 1.0 and r.by_tag["refund"] == (0.0, 1.0)
    log = tmp_path / "exp.md"
    append_log(log, hypothesis="good | prompt\nrefunds", change="prompt=good", model="scripted", result=r, decision="keep",
               hashes=("aaaa1111", "bbbb2222"))
    append_log(log, hypothesis="again", change="same", model="scripted", result=r)
    lines = log.read_text().splitlines()
    assert sum(l.startswith("| date") for l in lines) == 1 and len([l for l in lines if l.startswith("| 20")]) == 2
    assert "+100" in lines[-1] and "better" in lines[-1] and "8 × 2" in lines[-1]
    row = next(l for l in lines if "aaaa1111" in l)
    assert "good \\| prompt refunds" in row and "bbbb2222" in row, "pipes escaped, newlines removed, hashes logged"


def test_small_slices_are_insufficient_and_same_is_non_inferior(template_db):
    assert run_experiment(T[:2], factory, Variant("a"), Variant("b"), template_db=template_db, trials=1).verdict == "insufficient"
    same = run_experiment(T, factory, Variant("a"), Variant("b"), template_db=template_db, trials=1)
    assert same.verdict == "non-inferior", "identical variants: diff CI [0, 0] is within the margin"


def test_budget_stop_keeps_complete_pairs(template_db, monkeypatch):
    import agentlab.assistant.prompts as P
    from agentlab.costs import Budget
    monkeypatch.setitem(P.PROMPTS, "good", "GOOD prompt {today}")
    b = Budget(limit_usd=0.0)          # first charge crosses the cap; the scripted model is unpriced -> fallback price
    import pytest
    with pytest.raises(RuntimeError):
        run_experiment(T, factory, Variant("a"), Variant("b", prompt="good"), template_db=template_db, trials=1, budget=b)
