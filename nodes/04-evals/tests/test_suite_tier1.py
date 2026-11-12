"""TIER 1: tests the EVAL SUITE itself (TEXTBOOK §7). For every task, the golden script must pass and the bad script
must fail. A scripted 'judge' always answers pass, so judge graders are plumbing-tested here, not quality-tested."""
from pathlib import Path

import pytest

from agentlab.evals.runner import run_trial
from agentlab.evals.task import load_tasks, script_from_steps
from agentlab.llm.fake import ScriptedModel, say

SUITE = Path(__file__).resolve().parents[1] / "evals" / "support"
TASKS = load_tasks(SUITE, split=None)


class PassingJudge:
    provider, model = "fake", "judge"

    def complete(self, **kw):
        return say('{"reasoning": "scripted", "verdict": "pass"}')


def run(task, steps, template_db):
    sim = (lambda: ScriptedModel([say(m) for m in task.golden_user])) if task.user_sim else None
    return run_trial(task, ScriptedModel(script_from_steps(steps)), template_db=template_db,
                     judge_factory=PassingJudge, sim_factory=sim)


@pytest.mark.parametrize("task", TASKS, ids=[t.id for t in TASKS])
def test_golden_passes(task, template_db):
    assert task.golden, f"{task.id} has no golden script"
    t = run(task, task.golden, template_db)
    assert t.verdict == "pass", [(g.grader, g.verdict, g.detail) for g in t.grades]


BAD = [t for t in TASKS if t.bad]


@pytest.mark.parametrize("task", BAD, ids=[t.id for t in BAD])
def test_bad_fails(task, template_db):
    t = run(task, task.bad, template_db)
    assert t.verdict == "fail", f"graders didn't catch the bad script for {task.id}"
    failing = {g.grader.split("#")[0] for g in t.grades if g.verdict == "fail"}
    for g in task.bad_caught_by or []:
        assert g in failing, f"{task.id}: bad script should be caught by {g!r}, but failing graders were {failing}"


def test_enough_bad_scripts():
    assert len(BAD) >= 15, "every refund/escalation behaviour should have a bad script"
    assert all(t.bad_caught_by for t in BAD if t in TASKS), "say which grader must catch each bad script"
