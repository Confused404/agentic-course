"""python -m agentlab.reliability chaos | report | hitl-start | hitl-approve | hitl-resume | timeline   (SPEC §6)

  chaos   --model fast [--configs naive,retry,durable] [--seeds 3] [--fault-rate 0.2] [--crash-rate 0.1] [--budget 0.5]
  report  RUN_DIR
  hitl-start   --model fast                      start the over-$200 refund (order 4826); it pauses for approval
  hitl-approve RUN_ID CALL_ID --by NAME [--deny] [--note TEXT]
  hitl-resume  RUN_ID --model fast
  hitl-resolve RUN_ID CALL_ID --by NAME --result TEXT   record what a person found for a `needs_human` call
  timeline     RUN_ID [--journal PATH]           the run's history from its journal (free)
The HITL commands share runs/reliability/hitl/journal.db, and each run gets its own fresh copy of the shop
(runs/reliability/hitl/<RUN_ID>/shop.db), so each command can run in a NEW process (the point: the run survives the
process) and every hitl-start starts from the same shop state.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from agentlab.config import RUNS, new_run_dir

HITL_DIR = "reliability/hitl"
CONFIGS_DEFAULT = ("naive", "retry", "requeue", "durable")


def _hitl(run_id: str, model_alias: str | None, *, create: bool = False):
    from agentlab.assistant.prompts import get_prompt
    from agentlab.assistant.tools import make_support_tools
    from agentlab.reliability.chaos import shop_reconcilers
    from agentlab.reliability.durable import DurableAgent
    from agentlab.reliability.journal import Journal
    from shopfront import clock, db
    from shopfront.seed import build
    d = RUNS / HITL_DIR
    run_dir = d / run_id
    if create:
        template = d / "template" / "shop.db"
        if not template.exists():
            build(template, out_dir=d / "template" / "seed_side_files")
        run_dir.mkdir(parents=True, exist_ok=False)
        db.snapshot(template, run_dir / "shop.db")
    elif not (run_dir / "shop.db").exists():
        raise SystemExit(f"no HITL run {run_id!r} (looked in {run_dir})")
    conn = db.connect(run_dir / "shop.db")
    agent = DurableAgent(Journal(d / "journal.db"), make_support_tools(conn, 9006, actor="agent:hitl", variant="v2"),
                         approval_tools={"issue_refund"}, reconcilers=shop_reconcilers(conn, 9006))
    system = get_prompt("v2").replace("{today}", clock.now().date().isoformat())
    model = None
    if model_alias:
        from agentlab.llm.registry import get_model
        from agentlab.reliability.resilient import ResilientModel
        model = ResilientModel(get_model(model_alias))
    return agent, system, model


def _show(agent, r) -> None:
    print(f"{r.run_id}: {r.status} (stop={r.stop}, turns={r.turns}) {r.final_text[:300]}")
    for e in agent.pending_approvals(r.run_id):
        print(f"  waiting for approval: {e['call_id']} {e['tool']} {json.dumps(e['args'])}")
        print(f"  -> python -m agentlab.reliability hitl-approve {r.run_id} {e['call_id']} --by <you> [--deny]")
    if r.status == "needs_human":
        print(f"  can't tell whether {r.note} happened (no reconciler). Check the shop, then:")
        print(f"  -> python -m agentlab.reliability hitl-resolve {r.run_id} {r.note} --by <you> --result '<what happened>'")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m agentlab.reliability")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chaos")
    c.add_argument("--model", required=True)
    c.add_argument("--configs", default=",".join(CONFIGS_DEFAULT))
    c.add_argument("--seeds", type=int, default=3)
    c.add_argument("--fault-rate", type=float, default=0.2)
    c.add_argument("--crash-rate", type=float, default=0.1)
    c.add_argument("--budget", type=float, default=0.5)
    sub.add_parser("report").add_argument("run_dir")
    sub.add_parser("hitl-start").add_argument("--model", required=True)
    ap = sub.add_parser("hitl-approve")
    ap.add_argument("run_id")
    ap.add_argument("call_id")
    ap.add_argument("--by", required=True)
    ap.add_argument("--deny", action="store_true")
    ap.add_argument("--note", default="")
    rv = sub.add_parser("hitl-resolve")
    rv.add_argument("run_id")
    rv.add_argument("call_id")
    rv.add_argument("--by", required=True)
    rv.add_argument("--result", required=True, help="what actually happened, as the tool's result for the model")
    rs = sub.add_parser("hitl-resume")
    rs.add_argument("run_id")
    rs.add_argument("--model", required=True)
    tl = sub.add_parser("timeline")
    tl.add_argument("run_id")
    tl.add_argument("--journal", type=Path)
    a = p.parse_args(argv)

    from agentlab.reliability.chaos import CONFIGS, ChaosResult, render, run_chaos
    if a.cmd == "report":
        rows = [json.loads(x) for x in (Path(a.run_dir) / "results.jsonl").read_text().splitlines() if x.strip()]
        print(render([ChaosResult(**r) for r in rows]))
        return 0
    if a.cmd == "timeline":
        from agentlab.reliability.durable import timeline
        from agentlab.reliability.journal import Journal
        path = a.journal or RUNS / HITL_DIR / "journal.db"
        if not Path(path).exists():
            print(f"no journal at {path} yet: start a run first (hitl-start)")
            return 1
        j = Journal(path)
        es = j.entries(a.run_id)
        print(timeline(es) if es else f"no run {a.run_id!r}; runs: {', '.join(j.runs()) or 'none'}")
        return 0
    if a.cmd in ("hitl-start", "hitl-resume"):
        from agentlab.config import resolve
        resolve(a.model)
    if a.cmd == "hitl-start":
        from agentlab.llm.types import Message
        run_id = time.strftime("refund-4826-%Y%m%d-%H%M%S")
        agent, system, model = _hitl(run_id, a.model, create=True)
        _show(agent, agent.start(run_id, model, system, [Message.user("Order 4826 isn't what I wanted. Please "
                                                                      "refund it in full.")], max_turns=8))
        return 0
    if a.cmd == "hitl-approve":
        agent, _, _ = _hitl(a.run_id, None)
        agent.approve(a.run_id, a.call_id, not a.deny, a.by, a.note)
        print(f"recorded: {'DENIED' if a.deny else 'APPROVED'} by {a.by}. Resume with: "
              f"python -m agentlab.reliability hitl-resume {a.run_id} --model <alias>")
        return 0
    if a.cmd == "hitl-resume":
        agent, _, model = _hitl(a.run_id, a.model)
        _show(agent, agent.resume(a.run_id, model))
        return 0
    if a.cmd == "hitl-resolve":
        agent, _, _ = _hitl(a.run_id, None)
        agent.resolve_manually(a.run_id, a.call_id, a.result, a.by)
        print(f"recorded. Resume with: python -m agentlab.reliability hitl-resume {a.run_id} --model <alias>")
        return 0

    configs = [x for x in a.configs.split(",") if x]
    bad = [x for x in configs if x not in CONFIGS]
    if bad or not configs:
        raise ValueError(f"unknown config(s) {bad}; choose from {', '.join(CONFIGS)}")
    from agentlab.config import resolve
    resolve(a.model)
    from agentlab.costs import Budget, BudgetExceeded
    from agentlab.llm.registry import get_model
    from shopfront import db
    from shopfront.seed import build
    if a.seeds < 1 or not 0 <= a.fault_rate <= 1 or not 0 <= a.crash_rate <= 1:
        raise ValueError("--seeds must be >= 1; rates must be in [0, 1]")
    out = new_run_dir(RUNS / "reliability")
    build(out / "shop.db", out_dir=out / "seed_side_files")
    (out / "meta.json").write_text(json.dumps({"model": a.model, "configs": configs, "seeds": a.seeds,
                                               "fault_rate": a.fault_rate, "crash_rate": a.crash_rate}, indent=2))
    budget = Budget(limit_usd=a.budget, label="chaos")
    try:
        results = run_chaos(lambda: get_model(a.model),
                            lambda: db.connect(db.snapshot(out / "shop.db", out / "run.db")), configs=configs, seeds=tuple(range(a.seeds)), fault_rate=a.fault_rate,
                            crash_rate=a.crash_rate, budget=budget, out=out)
    except BudgetExceeded as e:
        print(f"! budget reached ({e}); reporting completed runs")
        rows = [json.loads(x) for x in (out / "results.jsonl").read_text().splitlines() if x.strip()]
        results = [ChaosResult(**r) for r in rows]
    md = render(results)
    (out / "report.md").write_text(md)
    print(md + f"\nresults: {out}  (spent ${budget.spent_usd:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
