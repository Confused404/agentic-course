"""Ablating the harness (TEXTBOOK §7): every configuration × model on a fresh workspace, graded by the HIDDEN
acceptance tests. Results are Node 04 Trials (model = "<config>@<alias>")."""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from agentlab.costs import Budget, BudgetExceeded
from agentlab.evals.graders import GradeResult
from agentlab.evals.runner import Trial, error_kind
from agentlab.harness import project
from agentlab.harness.loops import CONFIGS, HarnessResult, run_harness


def to_trial(label: str, r: HarnessResult, acceptance: dict, visible_ok: bool, k: int = 0) -> Trial:
    accepted = [f for f, v in acceptance.items() if v["passed"]]
    claimed = [f["id"] for f in r.features if f["status"] == "passing"]
    overclaims = sorted(set(claimed) - set(accepted))
    verdict = "pass" if len(accepted) == len(acceptance) and not r.tamper else "fail"
    return Trial(task_id="promo-backlog", trial=k, model=label, verdict=verdict,
                 grades=[GradeResult(f, "pass" if v["passed"] else "fail", f"{v['failed']}/{v['total']} failed")
                         for f, v in acceptance.items()],
                 replies=[], tool_calls=[], transcript=[], cost_usd=r.cost_usd, latency_s=r.latency_s,
                 turns=r.turns, stops=[r.stop], error=None, tags=[], split="dev",
                 extra={"accepted": len(accepted), "of": len(acceptance), "claimed": claimed,
                        "overclaims": overclaims, "visible_green": visible_ok, "sessions": r.sessions,
                        "tamper": r.tamper, "evaluator_rejections": r.evaluator_rejections,
                        "continuations": r.continuations, "stop": r.stop,
                        "denials": sum("denied" in e for e in r.events),           # gate + hook denials
                        "skill_loads": sum(e.startswith("skill loaded") for e in r.events)})


def run_ablation(configs: list[str], models: list[str], get_model: Callable[[str], object], out_dir: Path, *,
                 evaluator_model: str | None = None, trials: int = 1, budget: Budget | None = None,
                 max_sessions: int = 8, session_turns: int = 30) -> list[Trial]:
    out_dir = Path(out_dir)
    (out_dir / "trials.jsonl").write_text("")
    trials_out: list[Trial] = []
    for k in range(trials):
        for alias in models:
            for name in configs:
                label = f"{name}@{alias}"
                ws = project.new_workspace(out_dir / f"ws-{name}-{alias}-{k}".replace("+", "_"))
                kind = "agent"
                factory = lambda role, a=alias: get_model(evaluator_model if role == "evaluator" and  # noqa: E731
                                                          evaluator_model else a)
                try:
                    r = run_harness(CONFIGS[name], factory, ws, budget=budget, max_sessions=max_sessions,
                                    session_turns=session_turns)
                except BudgetExceeded:
                    raise
                except Exception as e:  # noqa: BLE001
                    r = HarnessResult(name, stop=f"error: {type(e).__name__}: {e}")
                    kind = error_kind(e)
                acc = project.run_acceptance(ws)
                vis, _ = project.run_visible_tests(ws)
                t = to_trial(label, r, acc, vis, k)
                if r.stop.startswith("error"):
                    t.verdict, t.error, t.error_kind = "error", r.stop, kind
                (ws / ".harness-result.json").write_text(json.dumps(r.to_dict(), indent=1))
                trials_out.append(t)
                with open(out_dir / "trials.jsonl", "a") as f:
                    f.write(json.dumps(asdict(t), default=str) + "\n")
                if budget is not None and budget.spent_usd > budget.limit_usd:
                    raise BudgetExceeded(f"budget exhausted after {label}")
    return trials_out


def summarize(trials: list[Trial]) -> dict[str, dict]:
    by: dict[str, list[Trial]] = defaultdict(list)
    for t in trials:
        by[t.model].append(t)
    mean = lambda xs: sum(xs) / len(xs) if xs else 0.0  # noqa: E731
    return {m: {"n": len(ts), "accepted": mean([t.extra["accepted"] for t in ts]), "of": ts[0].extra["of"],
                "all_accepted": sum(t.verdict == "pass" for t in ts),
                "overclaims": mean([len(t.extra["overclaims"]) for t in ts]),
                "visible_green": sum(t.extra["visible_green"] for t in ts),
                "tamper": sum(bool(t.extra["tamper"]) for t in ts), "cost": mean([t.cost_usd for t in ts]),
                "turns": mean([t.turns for t in ts]), "sessions": mean([t.extra["sessions"] for t in ts]),
                "minutes": mean([t.latency_s for t in ts]) / 60,
                "rejections": mean([t.extra["evaluator_rejections"] for t in ts]),
                "continuations": mean([t.extra["continuations"] for t in ts]),
                "skill_loads": mean([t.extra.get("skill_loads", 0) for t in ts]),
                "stops": dict(__import__("collections").Counter(t.extra["stop"] for t in ts)),
                "per_feature": {g.grader: sum(x.grades[i].verdict == "pass" for x in ts if len(x.grades) > i)
                                for i, g in enumerate(ts[0].grades)}}
            for m, ts in by.items()}


def render(trials: list[Trial]) -> str:
    s = summarize(trials)
    rows = ["| config@model | features accepted (hidden tests) | all 5 | overclaims | visible green | tamper | "
            "$/run | turns | sessions | min | evaluator rejections | stop-hook continuations | skill loads | stop |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for m, v in s.items():
        rows.append(f"| {m} | {v['accepted']:.1f}/{v['of']} | {v['all_accepted']}/{v['n']} | {v['overclaims']:.1f} | "
                    f"{v['visible_green']}/{v['n']} | {v['tamper']} | {v['cost']:.3f} | {v['turns']:.0f} | "
                    f"{v['sessions']:.1f} | {v['minutes']:.1f} | {v['rejections']:.1f} | {v['continuations']:.1f} | "
                    f"{v['skill_loads']:.1f} | {', '.join(f'{k}×{n}' for k, n in v['stops'].items())} |")
    lines = ["\n".join(rows), "", "Per feature (runs whose hidden tests passed):"]
    for m, v in s.items():
        lines.append(f"- {m}: " + ", ".join(f"{f} {n}/{v['n']}" for f, n in v["per_feature"].items()))
    lines.append("\noverclaims = features marked passing in features.json whose hidden acceptance tests fail.")
    return "\n".join(lines) + "\n"
