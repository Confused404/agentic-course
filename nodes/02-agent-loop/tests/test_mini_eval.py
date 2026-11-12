"""The mini eval runner: fresh DB per case, outcome checks from state."""
from pathlib import Path

from agentlab.evals.mini import Case, load_cases, run_case, run_suite, summarize
from agentlab.llm.fake import ScriptedModel, call, fail, say

CASES = Path(__file__).resolve().parents[1] / "evals" / "cases.yaml"


def test_cases_file_loads():
    cases = load_cases(CASES)
    assert len(cases) == 10 and cases[0].id == "c01_status" and cases[1].turns[1] == "Yes, please go ahead."


def test_passing_and_failing_refund_case(template_db):
    case = Case("r", 9001, ["refund 4822", "yes"], {"refund": {"order_id": 4822, "status": "issued"},
                                                     "tools_called": ["check_refund_eligibility"],
                                                     "refund_reasons_only": ["changed_mind"]})
    good = ScriptedModel([call("check_refund_eligibility", order_id=4822, reason="changed_mind"), say("eligible, ok?"),
                          call("issue_refund", order_id=4822, amount_cents=4899, reason="changed_mind"), say("done")])
    res = run_case(case, good, template_db=template_db)
    assert res.passed and all(res.checks.values()) and res.tools_called == ["check_refund_eligibility", "issue_refund"]
    liar = ScriptedModel([say("Done! Refunded."), say("Yes, all done.")])        # claims success, does nothing
    res = run_case(case, liar, template_db=template_db)
    assert not res.passed and res.checks["refund"] is False and res.checks["tools_called"] is False


def test_each_case_gets_a_fresh_db(template_db):
    case = Case("r", 9001, ["refund"], {"refund": {"order_id": 4822, "status": "issued"}})
    m = lambda: ScriptedModel([call("issue_refund", order_id=4822, amount_cents=100, reason="other"), say("ok")])  # noqa: E731
    results = run_suite([case, case], m, template_db=template_db, trials=2)
    assert len(results) == 4 and all(r.passed for r in results), "2nd run would fail (one refund per order) if DB were shared"
    import sqlite3
    assert sqlite3.connect(template_db).execute("SELECT count(*) FROM refunds WHERE order_id=4822").fetchone()[0] == 0


def test_other_checks(template_db):
    case = Case("x", 9003, ["cancel 4825; where is 4824?"],
                {"order_status": {"order_id": 4825, "status": "cancelled"}, "escalated": True,
                 "refund": {"order_id": 4824, "status": "none"}, "tools_not_called": ["issue_refund"],
                 "reply_contains_any": ["CANCELLED"], "reply_not_contains": ["refunded"]})
    m = ScriptedModel([call("cancel_order", order_id=4825),
                       call("escalate_to_human", summary="Order 4824 appears lost in transit.", order_id=4824),
                       say("Order 4825 is cancelled and I've escalated 4824.")])
    res = run_case(case, m, template_db=template_db)
    assert res.passed, res.checks


def test_model_error_is_captured_and_summary(template_db):
    case = Case("e", 9001, ["hi"], {})
    res = run_case(case, ScriptedModel([fail(RuntimeError("overloaded"))]), template_db=template_db)
    assert not res.passed and "overloaded" in res.error
    s = summarize([res])
    assert s["cases"] == 1 and s["passed"] == 0 and s["pass_rate"] == 0.0


def test_preexisting_refunds_do_not_count(template_db):
    case = Case("pre", 9004, ["hi"], {"refund": {"order_id": 4828, "status": "issued"}})   # seed already has one
    res = run_case(case, ScriptedModel([say("hello")]), template_db=template_db)
    assert res.checks["refund"] is False
