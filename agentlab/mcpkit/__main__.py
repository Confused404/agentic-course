"""python -m agentlab.mcpkit tools | lab | report   (Node 11 SPEC §6)

  tools  [--mode benign|poison|shadow|rug] [--listing N]   what the model would read from shopfront + parcel-rates:
                                                             each definition, its token cost, your review_tool()
                                                             findings, your Node 08 detector's score (for
                                                             comparison), fingerprint, and name collisions (free)
  lab    --model fast [--modes ...] [--defenses ...] [--scenarios ...] [--trials 1] [--budget 0.5]
  report RUN_DIR
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentlab.config import RUNS, new_run_dir


def _csv(v: str, allowed: tuple[str, ...], what: str) -> list[str]:
    items = [x for x in v.split(",") if x]
    bad = [x for x in items if x not in allowed]
    if bad or not items:
        raise ValueError(f"unknown {what} {bad or v!r}; choose from {', '.join(allowed)}")
    return items


def main(argv: list[str] | None = None) -> int:
    from agentlab.mcpkit import attack as A
    p = argparse.ArgumentParser(prog="python -m agentlab.mcpkit")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tools")
    t.add_argument("--mode", default="poison", choices=A.MODES)
    t.add_argument("--listing", type=int, default=1, help="which tools/list call to show (rug pulls change at 2)")
    lab = sub.add_parser("lab")
    lab.add_argument("--model", required=True)
    lab.add_argument("--modes", default=",".join(A.MODES))
    lab.add_argument("--defenses", default=",".join(A.DEFENSES))
    lab.add_argument("--scenarios", default=",".join(s.id for s in A.SCENARIOS))
    lab.add_argument("--trials", type=int, default=1)
    lab.add_argument("--budget", type=float, default=0.5)
    r = sub.add_parser("report")
    r.add_argument("run_dir")
    a = p.parse_args(argv)

    if a.cmd == "report":
        rows = [json.loads(x) for x in (Path(a.run_dir) / "results.jsonl").read_text().splitlines() if x.strip()]
        print(A.render([A.AttackResult(**x) for x in rows]))
        return 0

    from shopfront import db
    from shopfront.seed import build
    if a.cmd == "lab":
        from agentlab.config import resolve
        modes = _csv(a.modes, A.MODES, "mode")
        defenses = _csv(a.defenses, A.DEFENSES, "defense")
        ids = _csv(a.scenarios, tuple(s.id for s in A.SCENARIOS), "scenario")
        resolve(a.model)                                  # fail fast on a typo'd alias
    out = new_run_dir(RUNS / "mcp")
    build(out / "shop.db", out_dir=out / "seed_side_files")

    if a.cmd == "tools":
        from agentlab.context.tokens import estimate_tokens
        from agentlab.mcpkit.client import MCPToolset
        from agentlab.mcpkit.evil import EvilServer
        from agentlab.mcpkit.pins import fingerprint
        from agentlab.mcpkit.review import review_tool
        from agentlab.mcpkit.shop_server import build_shop_server
        from agentlab.security.detect import THRESHOLD, detect_injection
        evil = EvilServer(a.mode)
        evil.listings = a.listing - 1
        shop = build_shop_server(db.connect(out / "shop.db"), A.CUSTOMER)
        with MCPToolset({"shopfront": shop, "parcel-rates": evil.server}, namespace=False) as ts:
            total = 0
            defs = ts.tool_defs()
            for td in defs:
                tok = estimate_tokens(json.dumps({"name": td.name, "description": td.description,
                                                  "input_schema": td.input_schema}))
                total += tok
                score = detect_injection(td.description)
                findings = review_tool(td, defs)
                print(f"== {td.key}  ~{tok} tokens  fp {fingerprint(td)[:12]}\n"
                      f"   review: {[f'{f.rule}: {f.detail}' for f in findings] or 'nothing found'}\n"
                      f"   Node 08 detector: {score:.2f}{' (flagged)' if score >= THRESHOLD else ''}\n"
                      f"   annotations {td.annotations}\n   " + td.description.replace("\n", "\n   "))
            print(f"\ntotal ≈ {total} tokens of tool definitions on EVERY request")
            print(f"name collisions: {ts.collisions() or 'none'}")
            print(f"events: {ts.events or 'none'}")
        return 0

    from agentlab.costs import Budget, BudgetExceeded
    from agentlab.llm.registry import get_model
    scen = [s for s in A.SCENARIOS if s.id in ids]
    budget = Budget(limit_usd=a.budget, label="mcp-lab")

    def conn_factory():
        # why a fresh copy per run: refunds and escalations change the database (run_lab closes it after each run)
        return db.connect(db.snapshot(out / "shop.db", out / "run.db"))
    try:
        results = A.run_lab(lambda: get_model(a.model), conn_factory, modes=modes, defenses=defenses,
                            scenarios=scen, trials=a.trials, budget=budget, out=out)
    except BudgetExceeded as e:
        print(f"! budget reached ({e}); reporting completed runs")
        rows = [json.loads(x) for x in (out / "results.jsonl").read_text().splitlines() if x.strip()]
        results = [A.AttackResult(**x) for x in rows]
    md = A.render(results)
    (out / "report.md").write_text(md)
    print(md + f"\nresults: {out}  (spent ${budget.spent_usd:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
