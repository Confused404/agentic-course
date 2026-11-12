"""python -m agentlab.security detect-eval | attack | run | report   (Node 08 SPEC §7)

  detect-eval [--corpus PATH] [--split dev|heldout|all] [--threshold T]
  attack      --model ALIAS [--item ID] [--rounds 5] [--budget 0.2]        adaptive attacker vs YOUR detector
  run         --suite PATH --model ALIAS --defenses none,spotlight,filter,taint,plan [--trials 1] [--budget 1]
              [--split dev|heldout|all] [--tasks id,id]
  report      RUN_DIR
  show-attacks                                                             print the seeded attack texts
Every command except report accepts --template-db PATH to reuse a database (e.g. one you edited by hand).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentlab.config import ROOT, RUNS, new_run_dir

CORPUS = ROOT / "nodes" / "08-prompt-injection" / "evals" / "injections.yaml"


def _template(out: Path) -> Path:
    from shopfront.seed import build
    out.mkdir(parents=True, exist_ok=True)
    tmpl = out / "template.db"
    if not tmpl.exists():
        build(tmpl, out_dir=out / "seed_side_files")
    return tmpl


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m agentlab.security")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect-eval")
    d.add_argument("--corpus", default=str(CORPUS))
    d.add_argument("--split", default="dev")
    d.add_argument("--threshold", type=float, default=None)
    a = sub.add_parser("attack")
    a.add_argument("--model", required=True)
    a.add_argument("--corpus", default=str(CORPUS))
    a.add_argument("--item", default="db1201")
    a.add_argument("--rounds", type=int, default=5)
    a.add_argument("--budget", type=float, default=0.2)
    r = sub.add_parser("run")
    r.add_argument("--suite", required=True)
    r.add_argument("--model", required=True)
    r.add_argument("--defenses", default="none,spotlight,filter,taint,plan")
    r.add_argument("--trials", type=int, default=1)
    r.add_argument("--budget", type=float, default=1.0)
    r.add_argument("--split", default="dev")
    r.add_argument("--tasks", default="")
    rp = sub.add_parser("report")
    rp.add_argument("run_dir")
    sa = sub.add_parser("show-attacks")
    for sp in (d, a, r, sa):
        sp.add_argument("--template-db", default=None, help="reuse this seeded database instead of a fresh one")
    args = p.parse_args(argv)

    from agentlab.security import detect as det
    if args.cmd == "report":
        from agentlab.evals.runner import load_trials
        from agentlab.security.evals import render_security
        print(render_security(load_trials(Path(args.run_dir) / "trials.jsonl")))
        return 0
    if args.cmd == "run":
        from agentlab.security.ops import parse_defense
        defenses = [x for x in args.defenses.split(",") if x]
        for x in defenses:
            parse_defense(x)                    # fail fast, before seeding or spending
    import sqlite3
    out = new_run_dir(RUNS / "security")
    out.mkdir(parents=True, exist_ok=True)
    tmpl = Path(args.template_db) if args.template_db else _template(out)
    if args.cmd == "show-attacks":
        idx = json.loads((ROOT / "data" / "adversarial_index.json").read_text())
        c = sqlite3.connect(tmpl)
        q = {"reviews": "SELECT title || char(10) || body FROM reviews WHERE id = ?",
             "tickets": "SELECT subject || char(10) || body FROM tickets WHERE id = ?",
             "orders": "SELECT shipping_address FROM orders WHERE id = ?"}
        for it in idx:
            text = c.execute(q[it["table"]], (it["id"],)).fetchone()[0]
            shown = text.encode("unicode_escape").decode() if any(ord(ch) > 0xFFFF for ch in text) else text
            print(f"--- {it['table']} {it['id']}  {it['label']}  attack={it['is_attack']}\n{shown}\n")
        print(f"(database: {tmpl}; copy it, edit a row, and pass --template-db to run against your edit)")
        return 0
    if args.cmd == "detect-eval":
        from agentlab.security.evals import detector_eval, load_corpus
        items = load_corpus(args.corpus, sqlite3.connect(tmpl), None if args.split == "all" else args.split)
        th = args.threshold if args.threshold is not None else det.THRESHOLD
        res = detector_eval(items, det.detect_injection, th)
        print(f"{len(items)} items ({args.split}); threshold {th}: TPR {res['tpr']:.2f}  FPR {res['fpr']:.2f}")
        print("threshold sweep (TPR / FPR): " + "  ".join(f"{t:.1f}: {a:.2f}/{b:.2f}" for t, a, b in res["sweep"]))
        for i, lab, sc in res["missed"]:
            print(f"  MISSED  {i:22} {lab:24} {sc:.2f}")
        for i, lab, sc in res["false_alarms"]:
            print(f"  FALSE+  {i:22} {lab:24} {sc:.2f}")
    elif args.cmd == "attack":
        from agentlab.costs import Budget
        from agentlab.llm.registry import get_model
        from agentlab.security.evals import adaptive_attack, load_corpus
        items = {i["id"]: i for i in load_corpus(args.corpus, sqlite3.connect(tmpl))}
        it = items[args.item]
        if not it["is_attack"]:
            raise SystemExit(f"{args.item} is not an attack item")
        attempts = adaptive_attack(it["text"], f"the same action as this {it.get('label')} attack", det.detect_injection,
                                   det.THRESHOLD, get_model(args.model), args.rounds,
                                   Budget(limit_usd=args.budget, label="attack"))
        for at in attempts:
            print(f"--- round {at['round']} score {at['score']:.2f}{'  EVADED' if at['evaded'] else ''}\n{at['text']}")
        (out / "attack.json").write_text(json.dumps(attempts, indent=2))
    elif args.cmd == "run":
        from agentlab.costs import Budget, BudgetExceeded
        from agentlab.evals.runner import load_trials
        from agentlab.llm.registry import get_model
        from agentlab.security.evals import load_ops_tasks, render_security, run_ops
        tasks = load_ops_tasks(args.suite, None if args.split == "all" else args.split)
        if args.tasks:
            keep = set(args.tasks.split(","))
            tasks = [t for t in tasks if t.id in keep]
        (out / "meta.json").write_text(json.dumps({"model": args.model, "defenses": defenses, "split": args.split,
                                                   "trials": args.trials, "tasks": [t.id for t in tasks]}, indent=2))
        try:
            trials = run_ops(tasks, lambda: get_model(args.model), defenses, template_db=tmpl, trials=args.trials,
                             budget=Budget(limit_usd=args.budget, label="security"), out_dir=out)
        except BudgetExceeded as e:
            print(f"! budget reached ({e}); reporting completed trials")
            f = out / "trials.jsonl"
            trials = load_trials(f) if f.exists() else []
        md = render_security(trials) if trials else "no completed trials\n"
        (out / "report.md").write_text(md)
        print(md + f"results: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
