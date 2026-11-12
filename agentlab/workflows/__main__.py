"""python -m agentlab.workflows triage | report | draft   (Node 09 SPEC §6)

  triage  --methods rules,llm:fast,vote:fast:5,cascade:fast:5:0.8:mid,agent:fast [--split dev|heldout|all]
          [--hard-only] [--limit N] [--trials 1] [--budget 1] [--apply]
  report  RUN_DIR [--a M --b M] [--target 0.95]
  draft   --writer ALIAS --critic ALIAS [--tickets 1,2,3] [--rounds 3] [--budget 0.3]
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from agentlab.config import RUNS, new_run_dir


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m agentlab.workflows")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("triage")
    t.add_argument("--methods", required=True)
    t.add_argument("--split", default="dev", choices=["dev", "heldout", "all"])
    t.add_argument("--hard-only", action="store_true")
    t.add_argument("--limit", type=int, default=0)
    t.add_argument("--trials", type=int, default=1)
    t.add_argument("--budget", type=float, default=1.0)
    t.add_argument("--apply", action="store_true", help="write the LAST method's labels into a copy of the tickets table")
    r = sub.add_parser("report")
    r.add_argument("run_dir")
    r.add_argument("--a")
    r.add_argument("--b")
    r.add_argument("--target", type=float, default=0.95)
    r.add_argument("--slice", choices=["all", "easy", "hard"], default="all",
                   help="compare (--a/--b) and draw the coverage curve on this slice only")
    d = sub.add_parser("draft")
    d.add_argument("--writer", required=True)
    d.add_argument("--critic", required=True)
    d.add_argument("--tickets", default="211,212,216,217,226,232")
    d.add_argument("--rounds", type=int, default=3)
    d.add_argument("--budget", type=float, default=0.3)
    a = p.parse_args(argv)

    if a.cmd == "report":
        from agentlab.evals.report import compare
        from agentlab.evals.runner import load_trials
        from agentlab.workflows.evals import render
        trials = load_trials(Path(a.run_dir) / "trials.jsonl")
        if a.slice != "all":
            trials = [t for t in trials if a.slice in t.tags]
        print(render(trials, a.target))
        if a.a and a.b:
            c = compare(trials, a.a, a.b)
            print(f"{a.b} - {a.a}: {c['diff'] * 100:+.1f} pts [{c['lo'] * 100:+.1f}, {c['hi'] * 100:+.1f}] over "
                  f"{c['tasks']} tickets")
        return 0
    if a.cmd == "triage":
        methods = [m for m in a.methods.split(",") if m]
        from agentlab.config import resolve
        from agentlab.workflows.triage import method_aliases
        for m in methods:
            for alias in method_aliases(m):       # fail fast, before seeding or spending: a typo'd alias would
                resolve(alias)                    # otherwise turn every ticket into an "agent error" trial

    from agentlab.costs import Budget, BudgetExceeded
    from agentlab.llm.registry import get_model
    from agentlab.workflows.tickets import load_tickets
    from shopfront import db
    from shopfront.seed import build
    out = new_run_dir(RUNS / "workflows")
    out.mkdir(parents=True, exist_ok=True)
    build(out / "shop.db", out_dir=out / "seed_side_files")
    conn = db.connect(out / "shop.db")
    gold = out / "seed_side_files" / "ticket_gold.jsonl"
    if a.cmd == "triage":
        from agentlab.evals.runner import load_trials
        from agentlab.workflows.evals import render, run_triage
        tickets = load_tickets(conn, gold, None if a.split == "all" else a.split, True if a.hard_only else None)
        if a.limit:
            tickets = tickets[:a.limit]
        (out / "meta.json").write_text(json.dumps({"methods": methods, "split": a.split, "n": len(tickets),
                                                   "trials": a.trials}, indent=2))
        try:
            trials = run_triage(tickets, methods, get_model, conn=conn, trials=a.trials,
                                budget=Budget(limit_usd=a.budget, label="triage"), out_dir=out)
        except BudgetExceeded as e:
            print(f"! budget reached ({e}); reporting completed trials")
            f = out / "trials.jsonl"
            trials = load_trials(f) if f.exists() else []
        md = render(trials) if trials else "no completed trials\n"
        (out / "report.md").write_text(md)
        print(md + f"results: {out}")
        if a.apply and trials:
            last = [x for x in trials if x.model == methods[-1] and x.extra["pred"]]
            for x in last:
                pred = json.loads(x.replies[0])
                conn.execute("UPDATE tickets SET category = ?, priority = ? WHERE id = ?",
                             (pred["category"], pred["priority"], int(x.task_id)))
            conn.commit()
            print(f"applied {len(last)} labels to {out / 'shop.db'} (a copy; your data/shopfront.db is untouched)")
    elif a.cmd == "draft":
        from agentlab.workflows.drafting import draft_reply
        ids = {int(x) for x in a.tickets.split(",") if x}
        budget = Budget(limit_usd=a.budget, label="drafts")
        results = []
        for tk in [x for x in load_tickets(conn, gold) if x.id in ids]:
            res = draft_reply(get_model(a.writer), get_model(a.critic), tk, a.rounds, budget)
            results.append({"ticket": tk.id, **asdict(res)})
            print(f"--- ticket {tk.id} ({'passed' if res.passed else 'FAILED'} after {res.rounds} round(s), "
                  f"${res.cost_usd:.4f})\n{tk.body}\n>>> {res.final}\n")
            for h in res.history[:-1]:
                print(f"    round issues: {h['issues']}")
        (out / "drafts.json").write_text(json.dumps(results, indent=2))
        print(f"saved {out / 'drafts.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
