"""python -m agentlab.frameworks compare | report | graph-start | graph-resume | graph-show   (Node 16 SPEC §4)

  compare      --model fast [--impls native,pydantic-ai,langgraph] [--suite PATH] [--trials 1] [--budget 1.0]
  report       RUN_DIR
  graph-start  --model fast                   the over-$200 refund (order 4826) on LangGraph; pauses for approval
  graph-resume THREAD_ID --model fast --by NAME [--deny] [--note TEXT]
  graph-show   THREAD_ID                      the thread's checkpoints, newest first (free)
The graph-* commands share runs/frameworks/graph/ (checkpoints.db, and a shop per thread), so each can run in a NEW
process, like Node 14's hitl-* commands: compare the two.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from agentlab.config import ROOT, RUNS, models_config, new_run_dir, resolve

GRAPH_DIR = "frameworks/graph"
SUITE = "nodes/04-evals/evals/support/regression.yaml"


def _graph(thread: str, alias: str | None, *, create: bool = False):
    from agentlab.frameworks.graph_port import GraphSupportAssistant, sqlite_checkpointer
    from shopfront import db
    from shopfront.seed import build
    d = RUNS / GRAPH_DIR
    tdir = d / thread
    if create:
        tmpl = d / "template" / "shop.db"
        if not tmpl.exists():
            build(tmpl, out_dir=d / "template" / "seed_side_files")
        tdir.mkdir(parents=True, exist_ok=False)
        db.snapshot(tmpl, tdir / "shop.db")
    elif not (tdir / "shop.db").exists():
        raise SystemExit(f"no thread {thread!r} in {d}")
    model = None
    if alias:
        from agentlab.llm.registry import get_model
        from agentlab.reliability.resilient import ResilientModel
        model = ResilientModel(get_model(alias))       # like Node 14's hitl-* commands
    conn = db.connect(tdir / "shop.db")
    return GraphSupportAssistant(model, conn, 9006, checkpointer=sqlite_checkpointer(d / "checkpoints.db"),
                                 approval_tools=frozenset({"issue_refund"}), thread_id=thread)


def _show(a, r) -> None:
    print(f"{a.config['configurable']['thread_id']}: stop={r.result.stop} calls={r.result.turns}  {r.reply[:300]}")
    for p in a.pending_approvals():
        print(f"  waiting for approval: {p['call_id']} {p['tool']} {json.dumps(p['args'])}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m agentlab.frameworks")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compare")
    c.add_argument("--model", required=True)
    c.add_argument("--impls", default="native,pydantic-ai,langgraph")
    c.add_argument("--suite", default=SUITE)
    c.add_argument("--trials", type=int, default=1)
    c.add_argument("--budget", type=float, default=1.0)
    sub.add_parser("report").add_argument("run_dir")
    sub.add_parser("graph-start").add_argument("--model", required=True)
    gr = sub.add_parser("graph-resume")
    gr.add_argument("thread")
    gr.add_argument("--model", required=True)
    gr.add_argument("--by", required=True)
    gr.add_argument("--deny", action="store_true")
    gr.add_argument("--note", default="")
    sub.add_parser("graph-show").add_argument("thread")
    a = p.parse_args(argv)

    from agentlab.frameworks.compare import IMPLS, render, run_compare, summarize
    if a.cmd == "report":
        from agentlab.evals.runner import load_trials
        print(render(summarize(load_trials(Path(a.run_dir) / "trials.jsonl"))))
        return 0
    if a.cmd == "graph-show":
        from agentlab.frameworks.graph_port import sqlite_checkpointer
        path = RUNS / GRAPH_DIR / "checkpoints.db"
        if not path.exists():
            print("no checkpoints yet: run graph-start first")
            return 1
        saver = sqlite_checkpointer(path)
        cps = list(saver.list({"configurable": {"thread_id": a.thread}}))
        if not cps:
            print(f"no checkpoints for thread {a.thread!r}")
            return 1
        for cp in cps:
            msgs = cp.checkpoint["channel_values"].get("messages", [])
            last = msgs[-1] if msgs else {}
            kinds = [b.get("type") for b in last.get("content", [])]
            print(f"{cp.checkpoint['id'][:13]}  step {cp.metadata.get('step')}  messages {len(msgs)}  "
                  f"last: {last.get('role', '-')} {kinds}")
        return 0
    if a.cmd in ("compare", "graph-start", "graph-resume"):
        resolve(a.model)                                # unknown alias -> ValueError before anything is created
    if a.cmd == "graph-start":
        from agentlab.frameworks.graph_port import GraphSupportAssistant  # noqa: F401
        thread = time.strftime("refund-4826-%Y%m%d-%H%M%S")
        g = _graph(thread, a.model, create=True)
        _show(g, g.chat("Order 4826 isn't what I wanted. Please refund it in full."))
        print(f"  -> python -m agentlab.frameworks graph-resume {thread} --model {a.model} --by <you> [--deny]")
        return 0
    if a.cmd == "graph-resume":
        g = _graph(a.thread, a.model)
        pend = g.pending_approvals()
        if not pend:
            print("nothing is waiting for approval in this thread")
            return 1
        decisions = {x["call_id"]: {"approved": not a.deny, "by": a.by, "note": a.note} for x in pend}
        _show(g, g.resume(decisions))
        return 0

    impls = [i for i in a.impls.split(",") if i]
    bad = [i for i in impls if i not in IMPLS]
    if bad or not impls or a.trials < 1 or a.budget <= 0:
        raise ValueError(f"--impls from {', '.join(IMPLS)}; --trials >= 1; --budget > 0 (got {bad or a.impls})")
    from agentlab.costs import Budget
    from agentlab.evals.task import load_tasks
    from agentlab.llm.registry import get_model
    from shopfront.seed import build
    tasks = load_tasks(ROOT / a.suite if not Path(a.suite).is_absolute() else a.suite)
    out = new_run_dir(RUNS / "frameworks")
    build(out / "template.db", out_dir=out / "seed_side_files")
    ev = models_config().get("evals", {})
    judge, sim = ev.get("judge"), ev.get("user_sim")
    (out / "meta.json").write_text(json.dumps({"model": a.model, "resolved": ":".join(resolve(a.model)),
                                               "impls": impls, "suite": a.suite, "trials": a.trials}, indent=2))
    budget = Budget(limit_usd=a.budget, label="frameworks")
    try:
        trials = run_compare(tasks, impls, model_factory=lambda: get_model(a.model), alias=a.model,
                             template_db=out / "template.db", trials=a.trials, budget=budget,
                             judge_factory=(lambda: get_model(judge)) if judge else None,
                             sim_factory=(lambda: get_model(sim)) if sim else None, out_dir=out)
    except Exception as e:  # noqa: BLE001 - report what finished
        from agentlab.evals.runner import load_trials
        print(f"! stopped early: {type(e).__name__}: {e}")
        trials = load_trials(out / "trials.jsonl")
    md = render(summarize(trials))
    (out / "report.md").write_text(md)
    print(md + f"\nresults: {out}  (spent ${budget.spent_usd:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
