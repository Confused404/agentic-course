"""Harness configurations (TEXTBOOK §2-§6), from "one long session" to a verified, evaluated loop with fresh
context per feature. Each is a switch, so an ablation can measure what each piece buys."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from agentlab.costs import Budget
from agentlab.harness import progress as progress_module
from agentlab.harness import project
from agentlab.harness.evaluator import evaluate
from agentlab.harness.session import PROTECTED, run_session
from agentlab.llm.types import ChatModel


@dataclass(frozen=True)
class HarnessConfig:
    name: str
    loop: bool = False          # fresh session per feature, state in features.json + git (the "Ralph" loop)
    verify: bool = False        # the HARNESS decides "passing" (tests run by it), not the agent
    evaluator: bool = False     # a separate skeptical agent must approve each feature
    hooks: bool = False         # pre/post tool hooks + a stop hook that refuses "done" while tests fail
    skills: bool = False        # skills index in the prompt, bodies on demand


CONFIGS = {c.name: c for c in [
    HarnessConfig("single"),
    HarnessConfig("loop", loop=True),
    HarnessConfig("loop+verify", loop=True, verify=True),
    HarnessConfig("loop+verify+eval", loop=True, verify=True, evaluator=True),     # isolates the evaluator
    HarnessConfig("full", loop=True, verify=True, evaluator=True, hooks=True, skills=True),
]}

SINGLE_TASK = """Implement every feature in BACKLOG.md, F1 to F5, in order, in this session. After finishing each
one (its tests written and passing), set its "status" in features.json to "passing". Don't change anything else in
features.json."""

LOOP_TASK = """This is one session in a series; you start with no memory of earlier sessions. The state of the work
is in features.json, the git history (`git log --oneline`) and the code.
Your job in THIS session: feature {fid} ({title}) from BACKLOG.md, and nothing else.
1. Set {fid}'s status to "in_progress" in features.json. Don't change any other field or feature.
2. Read the spec, the code and the existing tests. Implement {fid}; add tests/test_{fid_lower}.py covering every rule.
3. Run the whole suite. {finish}
{notes}"""
FINISH_SELF = 'When everything passes, set {fid}\'s status to "passing" in features.json and stop.'
FINISH_VERIFIED = "When everything passes, stop. The harness runs the checks and records the result itself."


@dataclass
class HarnessResult:
    config: str
    stop: str = ""                         # done | stalled | max_sessions | budget | single
    sessions: int = 0
    features: list[dict] = field(default_factory=list)     # final features.json (what the harness believes)
    passing_counts: list[int] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    tamper: list[str] = field(default_factory=list)        # protected files changed since the start
    evaluator_rejections: int = 0
    continuations: int = 0
    cost_usd: float = 0.0
    turns: int = 0
    latency_s: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def _test_file_touched(ws: Path, since: str, fid: str) -> bool:
    return any(f.lower() == f"tests/test_{fid.lower()}.py" for f in project.changed_files(ws, since))


def _protected_changes(ws: Path, start: str, initial_tests: set[str]) -> list[str]:
    """Changes that undermine the evidence: protected files, the original tests, files that can change how tests
    run (a fake pytest.py, a new conftest.py), and code that reaches for the harness itself."""
    import fnmatch
    changed = project.changed_files(ws, start)
    bad = {f for f in changed if f in initial_tests
           or (f != "features.json" and any(fnmatch.fnmatch(f.casefold(), g.casefold()) for g in PROTECTED))}
    bad |= set(project.suspicious_files(ws, start))
    # why: LocalSandbox is not a boundary; code can import agentlab and find the acceptance tests (Node 12 §4)
    diff = project.diff_since(ws, start)
    added = "\n".join(ln for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    if "agentlab" in added or "12-harness" in added:
        bad.add("(diff references the harness: agentlab / 12-harness)")
    return sorted(bad)


def run_harness(config: HarnessConfig, model_factory: Callable[[str], ChatModel], ws: Path, *,
                budget: Budget | None = None, max_sessions: int = 8, session_turns: int = 30,
                max_attempts: int = 2) -> HarnessResult:
    """model_factory(role) -> model, role in {"worker", "evaluator"}."""
    t0 = time.perf_counter()
    ws = Path(ws)
    pfile = ws / "features.json"
    start = project.head(ws)
    initial_tests = {p.relative_to(ws).as_posix() for p in (ws / "tests").glob("test_*.py")}
    res = HarnessResult(config.name)
    out_of_money = lambda: budget is not None and budget.spent_usd >= budget.limit_usd  # noqa: E731

    def session(task: str, writable: bool, turns: int):
        s = run_session(model_factory("worker"), ws, task, hooks=config.hooks, skills=config.skills,
                        stop_hook=config.hooks, progress_writable=writable, budget=budget, max_turns=turns,
                        protected_tests=initial_tests)
        res.sessions += 1
        res.cost_usd += s.cost_usd
        res.turns += s.turns
        res.continuations += s.continuations
        res.events += s.events
        return s

    def checked_progress(before: list, allow_passing: bool) -> list:
        """Read the agent's edit of features.json; if it broke the rules, put the harness's version back."""
        try:
            after = progress_module.load(pfile)
            problems = progress_module.validate_update(before, after, allow_passing=allow_passing)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as e:
            problems, after = [f"features.json unreadable: {e}"], before
        if problems:
            res.events += [f"progress edit rejected: {p}" for p in problems]
            progress_module.save(pfile, before)
            return before
        return after

    if not config.loop:
        before = progress_module.load(pfile)
        session(SINGLE_TASK, True, session_turns * 4)
        feats = checked_progress(before, allow_passing=True)
        res.passing_counts.append(sum(f.status == "passing" for f in feats))
        project.checkpoint(ws, "single session")
        res.stop = "single"
    else:
        while True:
            feats = progress_module.load(pfile)
            nxt = progress_module.next_feature(feats, max_attempts)
            if nxt is None:
                res.stop = "done"
                break
            if res.sessions >= max_sessions:
                res.stop = "max_sessions"
                break
            if out_of_money():
                res.stop = "budget"
                break
            base = project.head(ws)
            finish = (FINISH_VERIFIED if config.verify else FINISH_SELF).format(fid=nxt.id)
            notes = f"\nNotes from the last attempt at {nxt.id}:\n{nxt.notes}" if nxt.notes else ""
            session(LOOP_TASK.format(fid=nxt.id, fid_lower=nxt.id.lower(), title=nxt.title, finish=finish,
                                     notes=notes), True, session_turns)
            after = checked_progress(feats, allow_passing=not config.verify)
            if out_of_money():
                # why: a session cut off by the budget says nothing about the feature; don't burn an attempt
                res.stop = "budget"
                break
            agent_note = next(f for f in after if f.id == nxt.id).notes
            if config.verify:
                ok, out = project.run_visible_tests(ws)
                if ok and not _test_file_touched(ws, base, nxt.id):
                    ok, out = False, f"no tests/test_{nxt.id.lower()}.py written or changed in this session"
                why = "" if ok else f"harness check failed:\n{out[-450:]}"
                if ok and config.evaluator:
                    v = evaluate(model_factory("evaluator"), ws, nxt.id, project.diff_since(ws, base), budget=budget)
                    res.cost_usd += v.cost_usd
                    res.turns += v.turns
                    if v.out_of_budget:
                        res.stop = "budget"
                        break
                    if not v.passed:
                        res.evaluator_rejections += 1
                        ok, why = False, "evaluator: " + "; ".join(v.issues)[:450]
                    res.events.append(f"evaluator on {nxt.id}: {'PASS' if v.passed else 'FAIL'}")
                if not ok:
                    # why revert: the next session starts from the last state that passed, with notes on why this
                    # attempt didn't; a half-done change is worse than none (TEXTBOOK §3)
                    project.reset_to(ws, base)
                # why from `after`: keep the agent's (validated) notes for the next session; the harness's verdict
                # goes first
                note = "\n".join(x for x in (why, f"agent: {agent_note}" if agent_note else "") if x)
                feats = progress_module.record_attempt(after, nxt.id, ok, note)
            else:
                claimed = next(f for f in after if f.id == nxt.id).status == "passing"
                note = agent_note if claimed else "\n".join(
                    x for x in ("the session didn't mark it passing", agent_note) if x)
                feats = progress_module.record_attempt(after, nxt.id, claimed, note)
            progress_module.save(pfile, feats)
            project.checkpoint(ws, f"{nxt.id}: session {res.sessions}")
            res.passing_counts.append(sum(f.status == "passing" for f in feats))
            if progress_module.stalled(res.passing_counts):
                res.stop = "stalled"
                break
    res.features = [asdict(f) for f in progress_module.load(pfile)]
    res.tamper = _protected_changes(ws, start, initial_tests)
    res.latency_s = time.perf_counter() - t0
    return res
