"""python -m agentlab.harness new | accept | run | report | show   (Node 12 SPEC §7)

  new    DEST                          a fresh promo workspace (for Claude Code / OpenCode runs, YOU_DO 6)
  accept WORKSPACE                     run the hidden acceptance tests against any workspace (free)
  run    --configs single,loop,loop+verify,loop+verify+eval,full --models fast [--evaluator-model mid] [--trials 1] [--budget 2]
         [--max-sessions 8] [--session-turns 30]
  report RUN_DIR [RUN_DIR ...]
  show   WORKSPACE                     the harness result, features.json, git log and diffstat of one run
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from agentlab.config import RUNS, new_run_dir


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m agentlab.harness")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("new").add_argument("dest", type=Path)
    sub.add_parser("accept").add_argument("workspace", type=Path)
    r = sub.add_parser("run")
    r.add_argument("--configs", default="single,loop,loop+verify,loop+verify+eval,full")
    r.add_argument("--models", default="fast")
    r.add_argument("--evaluator-model")
    r.add_argument("--trials", type=int, default=1)
    r.add_argument("--budget", type=float, default=2.0)
    r.add_argument("--max-sessions", type=int, default=8)
    r.add_argument("--session-turns", type=int, default=30)
    rp = sub.add_parser("report")
    rp.add_argument("run_dir", nargs="+")
    sub.add_parser("show").add_argument("workspace", type=Path)
    a = p.parse_args(argv)

    from agentlab.harness import project
    if a.cmd == "new":
        print(f"workspace: {project.new_workspace(a.dest)}")
        return 0
    if a.cmd == "accept":
        if not (a.workspace / "promo").is_dir():
            print(f"error: {a.workspace} is not a promo workspace (no promo/ directory)", file=sys.stderr)
            return 2
        acc = project.run_acceptance(a.workspace)
        for f, v in acc.items():
            print(f"{f}: {'PASS' if v['passed'] else 'FAIL'} ({v['failed']}/{v['total']} failed)")
        print(f"{sum(v['passed'] for v in acc.values())}/{len(acc)} features accepted")
        return 0
    if a.cmd == "report":
        from agentlab.evals.runner import load_trials
        from agentlab.harness.evals import render
        print(render([t for d in a.run_dir for t in load_trials(Path(d) / "trials.jsonl")]))
        return 0
    if a.cmd == "show":
        res = a.workspace / ".harness-result.json"
        if res.exists():
            d = json.loads(res.read_text())
            print(f"config {d['config']}: stop={d['stop']} sessions={d['sessions']} ${d['cost_usd']:.4f}")
            for e in d["events"]:
                print(f"  - {e}")
        print((a.workspace / "features.json").read_text())
        for args in (["log", "--oneline"], ["show", "--stat", "--format=", "HEAD"]):
            print(subprocess.run(["git", *args], cwd=a.workspace, capture_output=True, text=True).stdout)
        return 0

    from agentlab.config import resolve
    from agentlab.harness.loops import CONFIGS
    configs = [c for c in a.configs.split(",") if c]
    models = [m for m in a.models.split(",") if m]
    bad = [c for c in configs if c not in CONFIGS]
    if bad or not configs or not models:
        raise ValueError(f"unknown config(s) {bad}; choose from {', '.join(CONFIGS)}")
    for alias in models + ([a.evaluator_model] if a.evaluator_model else []):
        resolve(alias)                                   # fail fast, before spending
    from agentlab.costs import Budget, BudgetExceeded
    from agentlab.evals.runner import load_trials
    from agentlab.harness.evals import render, run_ablation
    from agentlab.llm.registry import get_model
    out = new_run_dir(RUNS / "harness")
    budget = Budget(limit_usd=a.budget, label="harness")
    try:
        trials = run_ablation(configs, models, get_model, out, evaluator_model=a.evaluator_model, trials=a.trials,
                              budget=budget, max_sessions=a.max_sessions, session_turns=a.session_turns)
    except BudgetExceeded as e:
        print(f"! budget reached ({e}); reporting completed runs")
        trials = load_trials(out / "trials.jsonl")
    md = render(trials) if trials else "no completed runs\n"
    (out / "report.md").write_text(md)
    print(md + f"\nresults and workspaces: {out}  (spent ${budget.spent_usd:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
