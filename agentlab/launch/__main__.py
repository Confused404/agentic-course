"""python -m agentlab.launch scorecard | gate | drill | serve   (Node 17 SPEC §6)

  scorecard [--evals DIR --evals-model M] [--perf DIR --perf-config C] [--security DIR --security-defense D]
            [--chaos DIR] [--human-cost 4.0] [--out scorecard.json]
  gate      [--scorecard scorecard.json] [--policy nodes/17-capstone/launch_policy.toml]   exit 0 = go, 1 = no-go
  drill     [--policy ...]                       game day with fakes and a simulated clock (free)
  serve     [--port 8001]                        the v2 API (needs LAUNCH_TOKEN_SECRET)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import tempfile
import tomllib
from pathlib import Path

from agentlab.config import ROOT, RUNS

POLICY = ROOT / "nodes" / "17-capstone" / "launch_policy.toml"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m agentlab.launch")
    sub = p.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scorecard")
    for flag in ("--evals", "--evals-model", "--perf", "--perf-config", "--security", "--security-defense",
                 "--chaos", "--chaos-config"):
        sc.add_argument(flag)
    sc.add_argument("--human-cost", type=float, default=4.0)
    sc.add_argument("--out", default=str(RUNS / "launch" / "scorecard.json"))
    g = sub.add_parser("gate")
    g.add_argument("--scorecard", default=str(RUNS / "launch" / "scorecard.json"))
    g.add_argument("--policy", default=str(POLICY))
    d = sub.add_parser("drill")
    d.add_argument("--policy", default=str(POLICY))
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=8001)
    a = p.parse_args(argv)

    if a.cmd == "scorecard":
        from agentlab.launch.scorecard import build_scorecard
        dirs = [a.evals, a.perf, a.security, a.chaos]
        if not any(dirs):
            raise ValueError("give at least one run dir (--evals/--perf/--security/--chaos)")
        for x in dirs:
            if x and not Path(x).is_dir():
                raise ValueError(f"not a run dir: {x}")
        card = build_scorecard(evals_dir=a.evals, evals_model=a.evals_model, perf_dir=a.perf,
                               perf_config=a.perf_config, security_dir=a.security,
                               security_defense=a.security_defense, chaos_dir=a.chaos,
                               chaos_config=a.chaos_config or "durable", human_cost_usd=a.human_cost)
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(card, indent=2))
        for k, v in card.items():
            print(f"{k:26} {v['value'] if v['value'] is not None else '–':>10}  {v['measured_at']}  {v['source']}")
        print(f"\nwritten: {out}")
        return 0
    if a.cmd == "gate":
        from agentlab.launch import gate as gate_module
        card = json.loads(Path(a.scorecard).read_text())
        rules = tomllib.loads(Path(a.policy).read_text()).get("rules", [])
        dec = gate_module.launch_decision(card, rules, now=dt.datetime.now(dt.timezone.utc))
        print("GO" if dec.go else "NO-GO")
        for title, items in (("blockers", dec.blockers), ("warnings", dec.warnings), ("passed", dec.passed)):
            for x in items:
                print(f"  {title[:-1]:8} {x}")
        return 0 if dec.go else 1
    if a.cmd == "drill":
        from agentlab.authz.tokens import issue_token
        from agentlab.launch.monitor import render_drill, run_drill
        import dataclasses
        from agentlab.launch.service import LaunchService, load_config
        from shopfront import db
        from shopfront.seed import build
        alerts = tomllib.loads(Path(a.policy).read_text()).get("alerts", {})
        tmp = Path(tempfile.mkdtemp(prefix="drill-"))
        build(tmp / "shop.db", out_dir=tmp / "seed")
        db.snapshot(tmp / "shop.db", tmp / "run.db")
        secret = b"drill-secret-drill-secret-drill-secret!!"
        # your launch.toml (max turns, budget, handover...), with everyone in the rollout and no kill switch
        cfg = dataclasses.replace(load_config(), rollout_percent=100.0, kill_switch=False)
        log = tmp / "events.jsonl"
        clock_ref = {"now": lambda: 1_000_000.0}

        def make_service(model_factory, clock):
            clock_ref["now"] = clock
            return LaunchService(cfg, secret, model_factory, lambda: db.connect(tmp / "run.db"), log_path=log,
                                 clock=clock)

        def token():
            return issue_token(secret, sub="customer:9001", audience=cfg.audience, scopes=["orders:read"],
                               now=int(clock_ref["now"]()), customer_id=9001)
        res = run_drill(make_service, token, alerts)
        print(render_drill(res))
        print(f"events: {log}")
        return 0
    if a.cmd == "serve":
        import uvicorn
        from agentlab.launch.server import create_app
        uvicorn.run(create_app(), port=a.port)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
