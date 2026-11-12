"""python -m agentlab.multi tasks | run | report | show   (Node 10 SPEC §5)

  tasks                                   the questions and their gold answers (free)
  run    --archs single:mid,orch:mid:fast,mapreduce:fast:mid [--tasks id,id] [--trials 1] [--budget 1]
         [--max-parallel 6]          an arch may carry a label: orch:fast:fast@brief2
  report RUN_DIR [RUN_DIR ...] [--baseline ARCH] [--a ARCH --b ARCH]     (several dirs are merged)
  show   RUN_DIR --task ID --arch ARCH [--trial 0] [--agent lead]   print one agent's transcript
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentlab.config import RUNS, new_run_dir


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m agentlab.multi")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tasks")
    r = sub.add_parser("run")
    r.add_argument("--archs", required=True)
    r.add_argument("--tasks", default="")
    r.add_argument("--trials", type=int, default=1)
    r.add_argument("--budget", type=float, default=1.0)
    r.add_argument("--max-parallel", type=int, default=6, help="workers at once (lower it on rate-limited free tiers)")
    rp = sub.add_parser("report")
    rp.add_argument("run_dir", nargs="+")
    rp.add_argument("--baseline")
    rp.add_argument("--a")
    rp.add_argument("--b")
    sh = sub.add_parser("show")
    sh.add_argument("run_dir")
    sh.add_argument("--task", required=True)
    sh.add_argument("--arch", required=True)
    sh.add_argument("--trial", type=int, default=0)
    sh.add_argument("--agent", default="")
    a = p.parse_args(argv)

    if a.cmd == "report":
        from agentlab.evals.report import compare
        from agentlab.evals.runner import load_trials
        from agentlab.multi.evals import render
        trials = [t for d in a.run_dir for t in load_trials(Path(d) / "trials.jsonl")]
        print(render(trials, a.baseline))
        if a.a and a.b:
            c = compare(trials, a.a, a.b)
            print(f"{a.b} - {a.a}: {c['diff'] * 100:+.1f} pts [{c['lo'] * 100:+.1f}, {c['hi'] * 100:+.1f}] over "
                  f"{c['tasks']} tasks")
        return 0
    if a.cmd == "show":
        safe = a.arch.replace(":", "_").replace("@", "_")
        f = Path(a.run_dir) / "transcripts" / f"{a.task}__{safe}__{a.trial}.json"
        transcripts = json.loads(f.read_text())
        names = [n for n in transcripts if not a.agent or n.startswith(a.agent)]
        if not names:
            print(f"no agent matching {a.agent!r}; agents: {', '.join(transcripts)}")
            return 1
        for n in names:
            print(f"===== {n}")
            for m in transcripts[n]:
                print(json.dumps(m, default=str)[:2000])
        return 0

    from agentlab.multi.tasks import TASKS
    selected = [t for t in TASKS if not a.tasks or t.id in a.tasks.split(",")]
    if a.tasks and len(selected) != len([x for x in a.tasks.split(",") if x]):
        raise ValueError(f"unknown task in {a.tasks!r}; tasks: {', '.join(t.id for t in TASKS)}")
    if a.cmd == "run":
        from agentlab.config import resolve
        from agentlab.multi.architectures import parse_arch
        archs = [x for x in a.archs.split(",") if x]
        for arch in archs:
            for alias in parse_arch(arch)[1]:      # fail fast: before seeding or spending
                resolve(alias)

    from shopfront import db
    from shopfront.seed import build
    out = new_run_dir(RUNS / "multi")
    build(out / "shop.db", out_dir=out / "seed_side_files")
    conn = db.connect(out / "shop.db")
    if a.cmd == "tasks":
        for t in selected:
            print(f"[{t.id}] ({t.answer_kind})\n  {t.question}\n  gold: {json.dumps(t.gold(conn))}\n")
        return 0

    from agentlab.costs import Budget, BudgetExceeded
    from agentlab.evals.runner import load_trials
    from agentlab.llm.registry import get_model
    from agentlab.multi.evals import render, run_multi
    (out / "meta.json").write_text(json.dumps({"archs": archs, "tasks": [t.id for t in selected],
                                               "trials": a.trials}, indent=2))
    try:
        trials = run_multi(selected, archs, get_model, conn, trials=a.trials,
                           budget=Budget(limit_usd=a.budget, label="multi"), out_dir=out,
                           max_parallel=a.max_parallel)
    except BudgetExceeded as e:
        print(f"! budget reached ({e}); reporting completed trials")
        f = out / "trials.jsonl"
        trials = load_trials(f) if f.exists() else []
    md = render(trials, archs[0]) if trials else "no completed trials\n"
    (out / "report.md").write_text(md)
    print(md + f"results: {out}")
    for t in trials:
        if t.verdict != "pass":
            print(f"  {t.model} on {t.task_id}: {t.verdict}: {t.grades[0].detail[:200] if t.grades else t.error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
