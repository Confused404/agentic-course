import json

import pytest

from agentlab.llm import fake
from agentlab.workflows import rules as rules_module
from agentlab.workflows.evals import macro_f1, render, run_triage, summarize


def test_macro_f1():
    assert macro_f1([("spam", "spam"), ("account", "account")]) == 1.0
    assert macro_f1([("spam", "spam"), ("account", None)]) == pytest.approx((1.0 + 0.0) / 2)


def test_run_and_summarize(tickets, json_model, monkeypatch, tmp_path, reference_selective):
    monkeypatch.setattr(rules_module, "classify_by_rules",
                        lambda text: rules_module.RuleResult("spam", "low", "x") if "SEO" in text else None)
    sub = [t for t in tickets if t.split == "dev"][:12]
    m = json_model([t.category for t in sub])          # an oracle in ticket order: always right
    trials = run_triage(sub, ["rules", "llm:x"], lambda a: m, out_dir=tmp_path)
    assert len(trials) == 24 and len((tmp_path / "trials.jsonl").read_text().splitlines()) == 24
    s = summarize(trials)
    assert s["llm:x"]["accuracy"] == 1.0 and s["llm:x"]["coverage"] == 1.0
    assert s["rules"]["coverage"] < 1.0 and s["rules"]["cost_per_ticket"] == 0
    md = render(trials)
    assert "| rules |" in md and "| llm:x |" in md
    from agentlab.evals.report import compare
    compare(trials, "rules", "llm:x")


def test_acceptable_secondary_counts(tickets, json_model):
    t = next(t for t in tickets if t.secondary and t.secondary[0] != "other")
    trials = run_triage([t], ["llm:x"], lambda a: json_model([t.secondary[0]]))
    assert trials[0].verdict == "pass" and trials[0].extra["strict"] is False


def test_crashing_rules_are_errors_not_abstentions(tickets, monkeypatch):
    def boom(text):
        raise KeyError("oops")
    monkeypatch.setattr(rules_module, "classify_by_rules", boom)
    tr = run_triage(tickets[:1], ["rules"], lambda a: None)[0]
    assert tr.verdict == "error", "only a deliberate abstention (None) is 'no answer, no error'"


def test_summary_separates_abstentions_and_mistakes(tickets, json_model, monkeypatch, reference_selective):
    monkeypatch.setattr(rules_module, "classify_by_rules", lambda text: None)
    sub = [t for t in tickets if t.split == "dev"][:4]
    trials = run_triage(sub, ["rules"], lambda a: None) + run_triage(sub, ["llm:x"], lambda a: json_model(["spam"]))
    s = summarize(trials)
    assert s["rules"]["stages"] == {"abstain": 4} and s["rules"]["confusion"] == {}
    assert all(p == "spam" for (_, p) in s["llm:x"]["confusion"]), "confusions are mistakes, never →None"
    assert "strict_accuracy" in s["llm:x"]


def test_run_dir_file_is_fresh(tickets, json_model, tmp_path):
    (tmp_path / "trials.jsonl").write_text("stale line\n")
    run_triage(tickets[:2], ["llm:x"], lambda a: json_model(["spam"]), out_dir=tmp_path)
    assert len((tmp_path / "trials.jsonl").read_text().splitlines()) == 2


def test_unparseable_is_an_agent_error(tickets, json_model):
    tr = run_triage(tickets[:1], ["llm:x"], lambda a: json_model([None]))[0]
    assert tr.verdict == "error" and tr.error_kind == "agent"


def test_drafting_loop(tickets):
    from agentlab.workflows.drafting import draft_reply
    t = tickets[0]
    writer = fake.ScriptedModel([fake.say("Your refund has been issued!"), fake.say("We'll look into it.")])
    critic = fake.ScriptedModel([fake.say(json.dumps({"pass": False, "issues": ["2: promises a refund"]})),
                                 fake.say(json.dumps({"pass": True, "issues": []}))])
    r = draft_reply(writer, critic, t, max_rounds=3)
    assert r.passed and r.rounds == 2 and r.final == "We'll look into it."
    assert "promises a refund" in writer.calls[1]["messages"][-1].text, "issues fed back to the writer"
    stuck = draft_reply(fake.ScriptedModel([fake.say("x")] * 2), fake.ScriptedModel([fake.say("garbage")] * 2), t,
                        max_rounds=2)
    assert not stuck.passed and stuck.rounds == 2, "an unreadable verdict is not a pass"
    stringy = draft_reply(fake.ScriptedModel([fake.say("x")]), fake.ScriptedModel(
        [fake.say(json.dumps({"pass": "false", "issues": []}))]), t, max_rounds=1)
    assert not stringy.passed, '"false" (a string) is not a pass'



def test_cli_fails_fast(tmp_path, monkeypatch):
    import agentlab.workflows.__main__ as cli
    monkeypatch.setattr(cli, "RUNS", tmp_path)
    with pytest.raises(ValueError):
        cli.main(["triage", "--methods", "rules,vote:fast"])
    with pytest.raises(ValueError):
        cli.main(["triage", "--methods", "llm:fsat"])          # a typo'd alias fails before any run starts
    assert not (tmp_path / "workflows").exists()
