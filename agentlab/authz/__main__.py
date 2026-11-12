"""python -m agentlab.authz gate-eval | report | token-issue | token-verify   (Node 13 SPEC §5)

  gate-eval --methods rules:block,rules:allow,classifier:fast:3,two-stage:fast:3:1.0 [--extra FILE.yaml]
            [--skip-denied] [--budget 0.5]
  report    RUN_DIR [RUN_DIR ...]
  token-issue  --sub customer:9001 --cid 9001 --scopes orders:read,refunds:write [--aud shopfront-mcp] [--ttl 900]
  token-verify TOKEN [--aud shopfront-mcp] [--scopes orders:read]
Tokens use AGENTLAB_TOKEN_SECRET from .env (a fixed dev secret, with a warning, if unset).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from agentlab.config import ROOT, RUNS, new_run_dir

DEV_SECRET = b"dev-only-secret-do-not-use-in-production"


def _secret() -> bytes:
    s = os.environ.get("AGENTLAB_TOKEN_SECRET")
    if not s:
        print("! AGENTLAB_TOKEN_SECRET not set: using the built-in DEV secret", file=sys.stderr)
        return DEV_SECRET
    return s.encode()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m agentlab.authz")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate-eval")
    g.add_argument("--methods", default="rules:block,rules:allow")
    g.add_argument("--extra", type=Path, help="your own labelled actions (same format), appended")
    g.add_argument("--skip-denied", action="store_true",
                   help="drop items Node 03's rules deny (they never reach the classifier); keeps rule-ALLOWED ones")
    g.add_argument("--budget", type=float, default=0.5)
    r = sub.add_parser("report")
    r.add_argument("run_dir", nargs="+")
    ti = sub.add_parser("token-issue")
    ti.add_argument("--sub", required=True)
    ti.add_argument("--cid", type=int)
    ti.add_argument("--scopes", default="")
    ti.add_argument("--aud", default="shopfront-mcp")
    ti.add_argument("--ttl", type=int, default=900)
    tv = sub.add_parser("token-verify")
    tv.add_argument("token")
    tv.add_argument("--aud", default="shopfront-mcp")
    tv.add_argument("--scopes", default="")
    a = p.parse_args(argv)

    if a.cmd == "token-issue":
        from agentlab.authz.tokens import issue_token
        print(issue_token(_secret(), sub=a.sub, audience=a.aud, scopes=[s for s in a.scopes.split(",") if s],
                          now=int(time.time()), ttl_s=a.ttl, customer_id=a.cid))
        return 0
    if a.cmd == "token-verify":
        from agentlab.authz.tokens import TokenError, verify_token
        try:
            pr = verify_token(a.token, _secret(), audience=a.aud, now=int(time.time()),
                              required_scopes={s for s in a.scopes.split(",") if s})
        except TokenError as e:
            print(f"REJECTED {e.code}: {e}")
            return 1
        print(f"OK {pr}")
        return 0
    if a.cmd == "report":
        from agentlab.authz.evals import render
        from agentlab.evals.runner import load_trials
        print(render([t for d in a.run_dir for t in load_trials(Path(d) / "trials.jsonl")]))
        return 0

    from agentlab.authz.evals import load_actions, parse_method, render, run_gate_eval
    from agentlab.config import resolve
    methods = [m for m in a.methods.split(",") if m]
    for m in methods:
        name, args = parse_method(m)
        if name != "rules":
            resolve(args[0])                         # fail fast before spending
    items = load_actions() + (load_actions(a.extra) if a.extra else [])
    if a.skip_denied:
        from agentlab.shopdev.permissions import PermissionGate
        items = [i for i in items if PermissionGate(ROOT).decide("run_shell", {"command": i.command}).action != "deny"]
    from agentlab.costs import Budget, BudgetExceeded
    from agentlab.evals.runner import load_trials
    from agentlab.llm.registry import get_model
    out = new_run_dir(RUNS / "authz")
    budget = Budget(limit_usd=a.budget, label="gate-eval")
    try:
        trials = run_gate_eval(items, methods, get_model, ROOT, budget=budget, out_dir=out)
    except BudgetExceeded as e:
        print(f"! budget reached ({e}); reporting completed decisions")
        trials = load_trials(out / "trials.jsonl")
    md = render(trials)
    (out / "report.md").write_text(md)
    print(md + f"\n{len(items)} actions; results: {out}  (spent ${budget.spent_usd:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
