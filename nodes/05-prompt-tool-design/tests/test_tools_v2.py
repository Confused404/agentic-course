"""Your v2 tool design (docs/design/support-tools-v2.md), as implemented by your coding agent."""
import json
import re

import pytest

from agentlab.assistant.tools import make_support_tools
from agentlab.config import ROOT
from agentlab.evals.runner import run_trial
from agentlab.evals.task import load_tasks, script_from_steps
from agentlab.llm.fake import ScriptedModel, say
from agentlab.llm.types import ToolUseBlock
from agentlab.tools.lint import lint_tools

SUITE = ROOT / "nodes" / "04-evals" / "evals" / "support"


DOC = ROOT / "docs" / "design" / "support-tools-v2.md"
norm = lambda s: re.sub(r"\s+", " ", s or "").strip()  # noqa: E731


def test_design_doc_exists():
    assert DOC.exists() and len(DOC.read_text()) > 800, "write the design first (YOU_DO task 2)"


def test_v2_implements_the_design_doc_verbatim(conn):
    """Every v2 tool description and parameter description must appear in YOUR design doc (whitespace-insensitive).
    The doc is the source of truth; the coding agent implements it, it doesn't redesign it."""
    doc = norm(DOC.read_text())
    for s in make_support_tools(conn, 9001, variant="v2").specs():
        assert norm(s.description) in doc, f"{s.name}: description not found verbatim in the design doc"
        for p, ps in s.input_schema["properties"].items():
            assert norm(ps.get("description")) in doc, f"{s.name}.{p}: parameter description not in the design doc"


def test_v2_keeps_names_bindings_and_is_lint_clean(conn):
    v1, v2 = make_support_tools(conn, 9001), make_support_tools(conn, 9001, variant="v2")
    assert set(v1.names()) <= set(v2.names()), "the eval suite references v1 tool names"
    for s1 in v1.specs():
        s2 = next(s for s in v2.specs() if s.name == s1.name)
        assert set(s1.input_schema["properties"]) <= set(s2.input_schema["properties"])
        assert set(s2.input_schema.get("required", [])) <= set(s1.input_schema.get("required", [])), "no new required params"
    for s in v2.specs():
        assert "customer_id" not in s.input_schema.get("properties", {})
    findings = lint_tools(v2.specs())
    assert not findings, [f"{f.level} {f.where} {f.rule}" for f in findings]


@pytest.mark.parametrize("name,args", [("lookup_order", {"order_id": 99999}),
                                       ("issue_refund", {"order_id": 4821, "amount_cents": 100, "reason": "changed_mind"}),
                                       ("cancel_order", {"order_id": 4824})])
def test_v2_errors_are_structured_with_next_steps(conn, name, args):
    r = make_support_tools(conn, 9001, variant="v2").execute(ToolUseBlock("t", name, args))
    assert r.is_error
    body = json.loads(r.content)
    assert re.fullmatch(r"[A-Z][A-Z0-9_]+", body["error"]), "any UPPER_SNAKE code; finer codes are welcome"
    assert len(body["message"]) > 20
    assert isinstance(body["next_steps"], list) and body["next_steps"] and all(len(s) > 5 for s in body["next_steps"])


def test_v2_validation_errors_use_the_same_shape(conn):
    r = make_support_tools(conn, 9001, variant="v2").execute(
        ToolUseBlock("t", "check_refund_eligibility", {"order_id": 4821, "reason": "broken"}))
    body = json.loads(r.content)
    assert r.is_error and body["next_steps"] and "reason" in body["message"]


def test_partial_variants_for_one_change_experiments(conn):
    for v in ("v1+desc", "v1+errors", "v1+desc+errors", "v1+returns"):
        assert make_support_tools(conn, 9001, variant=v).names() == make_support_tools(conn, 9001).names()
    d = make_support_tools(conn, 9001, variant="v1+desc")
    e = make_support_tools(conn, 9001, variant="v1+errors")
    assert d.get("issue_refund").description == make_support_tools(conn, 9001, variant="v2").get("issue_refund").description
    assert e.get("issue_refund").description == make_support_tools(conn, 9001).get("issue_refund").description
    assert json.loads(e.execute(ToolUseBlock("t", "lookup_order", {"order_id": 99999})).content)["next_steps"]
    with pytest.raises(ValueError):
        make_support_tools(conn, 9001, variant="v1+vibes")


class PassingJudge:
    provider, model = "fake", "judge"

    def complete(self, **kw):
        return say('{"reasoning": "scripted", "verdict": "pass"}')


TASKS = load_tasks(SUITE)


@pytest.mark.parametrize("task", TASKS, ids=[t.id for t in TASKS])
def test_suite_golden_scripts_still_pass_with_v2_tools(task, template_db):
    sim = (lambda: ScriptedModel([say(m) for m in task.golden_user])) if task.user_sim else None
    t = run_trial(task, ScriptedModel(script_from_steps(task.golden)), template_db=template_db,
                  judge_factory=PassingJudge, sim_factory=sim, assistant_opts={"tool_variant": "v2"})
    assert t.verdict == "pass", [(g.grader, g.detail) for g in t.grades if g.verdict != "pass"]
