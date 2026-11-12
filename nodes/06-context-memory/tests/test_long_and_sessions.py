"""End-to-end, offline: the oracle model can only use what's in its window, so these show which strategies lose the
plant. (Your live runs will show the same thing with real models, plus everything an oracle can't: paraphrase,
distraction, and summaries that sound right and aren't.)"""
from pathlib import Path

import pytest
import yaml

from agentlab.context.longconv import KINDS, LENGTHS, generate_suite, make_long_task
from agentlab.context.strategies import Compaction
from agentlab.evals.graders import TrialContext, grade
from agentlab.evals.runner import run_trial
from agentlab.evals.task import Task, load_tasks

NODE = Path(__file__).resolve().parents[1]


def test_generator_shape_and_determinism():
    for k in KINDS:
        for n in LENGTHS:
            t = make_long_task(k, n)
            assert len(t["turns"]) == n and t["turns"][1].startswith(("Heads up", "One rule", "Order 4831"))
            assert make_long_task(k, n) == t
    assert make_long_task("constraint_revoked", 30)["turns"].count(
        "You can drop the CONFIRM rule I gave you earlier; no need for it anymore.") == 1
    with pytest.raises(ValueError):
        make_long_task("constraint", 3)


def test_shipped_suites_load():
    shipped = yaml.safe_load((NODE / "evals/long/long.yaml").read_text())
    assert shipped == generate_suite(), "regenerate with `python -m agentlab.context gen`"
    assert len(load_tasks(NODE / "evals/long")) == 12
    mem = load_tasks(NODE / "evals/memory")
    assert len(mem) >= 8 and all(t.sessions for t in mem)


def test_task_validation():
    from agentlab.evals.task import _validate
    with pytest.raises(ValueError):
        _validate(Task("x", 1, [{"type": "no_side_effects"}], turns=["a"], sessions=[["b"]]))
    with pytest.raises(ValueError):
        _validate(Task("x", 1, [{"type": "no_side_effects"}], sessions=[["a"], []]))
    _validate(Task("x", 1, [{"type": "no_side_effects"}], sessions=[["a"], ["b"]]))


def run_long(kind, n, opts, template_db, oracle):
    t = Task(**make_long_task(kind, n))
    return run_trial(t, oracle(), template_db=template_db, assistant_opts=opts)


@pytest.mark.parametrize("kind", ["refund_recall", "alias_action"])
def test_full_history_passes(kind, template_db, oracle):
    tr = run_long(kind, 30, {"context": "full"}, template_db, oracle)
    assert tr.verdict == "pass", tr.grades
    stats = tr.extra["turn_stats"]
    assert len(stats) == 30 and stats[-1]["est_after"] > stats[1]["est_after"], "context grows every turn"


@pytest.mark.parametrize("kind", ["refund_recall", "alias_action"])
def test_window_loses_the_plant(kind, template_db, oracle):
    tr = run_long(kind, 30, {"context": "window:4"}, template_db, oracle)
    assert tr.verdict == "fail" and tr.extra["context_actions"] == ["dropped"]
    assert len(tr.transcript) > 60, "the TRANSCRIPT is complete even though the model saw only 4 turns"


@pytest.mark.parametrize("kind", ["refund_recall", "alias_action"])
def test_good_compaction_keeps_it(kind, template_db, oracle, keyword_summarizer):
    tr = run_long(kind, 30, {"context": Compaction(keyword_summarizer(), "P", trigger_tokens=6000, keep_turns=3)},
                  template_db, oracle)
    assert tr.verdict == "pass", tr.grades
    assert "compacted" in tr.extra["context_actions"]
    summaries = [s["summary"] for s in tr.extra["turn_stats"] if s.get("summary")]
    assert summaries, "the summary the model saw is recorded, so you can read it"
    n = sum(s["action"] == "compacted" for s in tr.extra["turn_stats"])
    assert n <= 8, f"compacted {n} times in 30 turns: compaction must act in large steps, not every turn"
    peak = max(s["est_after"] for s in tr.extra["turn_stats"])
    full = run_long(kind, 30, {"context": "full"}, template_db, oracle)
    assert peak < max(s["est_after"] for s in full.extra["turn_stats"]) / 2, "and the context stays small"


def test_clear_tool_results_keeps_customer_text(template_db, oracle):
    tr = run_long("refund_recall", 30, {"context": "clear:3000:2"}, template_db, oracle)
    assert tr.verdict == "pass" and "cleared" in tr.extra["context_actions"]


def test_sessions_and_memory(template_db, oracle, extractor):
    t = next(x for x in load_tasks(NODE / "evals/memory") if x.id == "mem_name")
    off = run_trial(t, oracle(), template_db=template_db, assistant_opts={"memory": "off"})
    assert off.verdict == "fail", "without memory, session 2 knows nothing"
    on = run_trial(t, oracle(), template_db=template_db,
                   assistant_opts={"memory": "on", "memory_model": extractor()})
    assert on.verdict == "pass", on.grades
    assert [w["action"] for w in on.extra["memory_writes"]] == ["store"]
    assert {s["session"] for s in on.extra["turn_stats"]} == {0, 1}


def test_memory_and_scope_graders(conn):
    from agentlab.memory.store import MemoryStore
    ctx = TrialContext(conn, {}, [], ["Hola Pree", "Hello"], 9003, last_session_replies=["Hello"])
    assert grade({"type": "memory_absent", "pattern": "."}, ctx).verdict == "pass", "no table = no memories"
    assert grade({"type": "memory_contains", "pattern": "x"}, ctx).verdict == "fail"
    MemoryStore(conn).add(9003, "preference", "Prefers Spanish.", "Spanish")
    MemoryStore(conn).add(9002, "preference", "Prefers French.", "French")
    assert grade({"type": "memory_contains", "pattern": "spanish"}, ctx).verdict == "pass"
    assert grade({"type": "memory_absent", "pattern": "french"}, ctx).verdict == "pass", "other customers' don't count"
    assert grade({"type": "reply_not_regex", "pattern": "pree"}, ctx).verdict == "fail"
    assert grade({"type": "reply_not_regex", "pattern": "pree", "scope": "last_session"}, ctx).verdict == "pass"
    assert grade({"type": "reply_regex", "pattern": "hola"}, ctx).verdict == "fail", "default: final reply"
    assert grade({"type": "reply_regex", "pattern": "hola", "scope": "any"}, ctx).verdict == "pass"


def test_old_trials_still_load(tmp_path):
    import json
    from agentlab.evals.runner import load_trials
    old = {"task_id": "t", "trial": 0, "model": "m", "verdict": "pass", "grades": [], "replies": [], "tool_calls": [],
           "transcript": [], "cost_usd": 0, "latency_s": 0, "turns": 1, "stops": [], "error": None, "tags": [],
           "split": "dev"}
    (tmp_path / "t.jsonl").write_text(json.dumps(old) + "\n")
    assert load_trials(tmp_path / "t.jsonl")[0].extra == {}


def test_graders_read_the_transcript_not_the_window(template_db):
    """An early tool call must still be visible to graders after the window has dropped it."""
    from agentlab.llm import fake
    t = Task("early_lookup", 9003, [{"type": "tools_called", "tools": ["lookup_order"]}],
             turns=["status of 4831?", "thanks", "and shipping times?", "bye"])
    model = fake.ScriptedModel([fake.call("lookup_order", order_id=4831), fake.say("delivered"), fake.say("ok"),
                                fake.say("3-5 days"), fake.say("bye")])
    tr = run_trial(t, model, template_db=template_db, assistant_opts={"context": "window:1"})
    assert tr.verdict == "pass", tr.grades
    assert "lookup_order" not in [b.name for m in model.calls[-1]["messages"] for b in m.content
                                  if hasattr(b, "name")], "the model no longer saw it"


def test_session_fold_happens_once_even_on_error(template_db):
    from agentlab.llm import fake
    t = Task("two", 9003, [{"type": "no_side_effects"}], sessions=[["hi"], ["again", "more"]])
    model = fake.ScriptedModel([fake.say("hello"), fake.say("hi again"), fake.fail(ValueError("boom"))])
    tr = run_trial(t, model, template_db=template_db)
    assert tr.verdict == "error" and "boom" in tr.error
    assert len(tr.transcript) == 5, "session 1 (2) + session 2 so far (2 + the failing user turn); folded once"
    assert [s["session"] for s in tr.extra["turn_stats"]] == [0, 1]


def test_memory_absent_include_superseded(conn):
    from agentlab.memory.store import MemoryStore
    st = MemoryStore(conn)
    a = st.add(9003, "preference", "Prefers to be called Pree.", "x")
    st.supersede(9003, a, st.add(9003, "preference", "Prefers Priya.", "y"))
    ctx = TrialContext(conn, {}, [], [], 9003)
    assert grade({"type": "memory_absent", "pattern": "pree"}, ctx).verdict == "pass"
    assert grade({"type": "memory_absent", "pattern": "pree", "include_superseded": True}, ctx).verdict == "fail"


def test_context_report_and_cli(template_db, oracle, tmp_path, capsys):
    import json
    from dataclasses import asdict

    from agentlab.context.__main__ import main
    from agentlab.context.report import summarize_context
    trials = []
    for label, opts in (("full", {"context": "full"}), ("window", {"context": "window:4"})):
        tr = run_long("refund_recall", 10, opts, template_db, oracle)
        tr.model = label
        trials.append(tr)
    s = summarize_context(trials)
    assert s["full"]["pass_rate"] == 1.0 and s["full"]["by_length"] == {"len10": 1.0}
    assert s["full"]["input_tokens_per_trial"] >= 0 and s["window"]["max_call_est_tokens"] < s["full"]["max_call_est_tokens"]
    (tmp_path / "trials.jsonl").write_text("".join(json.dumps(asdict(t), default=str) + "\n" for t in trials))
    assert main(["report", str(tmp_path)]) == 0
    assert (tmp_path / "context_report.md").exists()
    rows = (tmp_path / "tokens_by_turn.csv").read_text().splitlines()
    assert rows[0].startswith("variant,task,trial,session,turn") and len(rows) == 1 + 20
    assert main(["breakdown", str(tmp_path), "--task", "long_refund_recall_10", "--variant", "full"]) == 0
    out = capsys.readouterr().out
    assert "tool_results" in out and "system" in out
    with pytest.raises(SystemExit):
        main(["breakdown", str(tmp_path), "--task", "long_refund_recall_10"])     # ambiguous: two variants
