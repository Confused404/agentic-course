"""python -m agentlab.evals run|report|compare|mine  (see nodes/04-evals/SPEC.md §9)"""
from __future__ import annotations

import argparse
from pathlib import Path

from agentlab.config import ROOT, RUNS, new_run_dir, models_config


def main() -> None:
    ap = argparse.ArgumentParser(prog="evals")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--suite", required=True)
    r.add_argument("--split", default="dev")
    r.add_argument("--tags", default="")
    r.add_argument("--models", required=True)
    r.add_argument("--trials", type=int, default=3)
    r.add_argument("--budget", type=float, default=2.0)
    r.add_argument("--judge", default=None)
    r.add_argument("--sim", default=None)
    r.add_argument("--prompt", default="v1")
    r.add_argument("--tools", default="v1")
    r.add_argument("--out", default=None)
    r.add_argument("--retry-errors", action="store_true", help="retry a trial once after a provider error/timeout")
    rp = sub.add_parser("report")
    rp.add_argument("run_dir")
    rp.add_argument("--k", type=int, default=3)
    c = sub.add_parser("compare")
    c.add_argument("runs", nargs="+")
    c.add_argument("--a")
    c.add_argument("--b")
    c.add_argument("--model")
    e = sub.add_parser("experiment")
    e.add_argument("--suite", required=True)
    e.add_argument("--model", required=True)
    e.add_argument("--baseline", required=True)
    e.add_argument("--candidate", required=True)
    e.add_argument("--split", default="dev")
    e.add_argument("--tags", default="")
    e.add_argument("--trials", type=int, default=3)
    e.add_argument("--budget", type=float, default=2.0)
    e.add_argument("--hypothesis", default="")
    e.add_argument("--change", default="")
    e.add_argument("--log", default="docs/experiments/node05.md")
    e.add_argument("--decision", default="")
    e.add_argument("--margin", type=float, default=0.05, help="non-inferiority margin (0.05 = 5 points)")
    e.add_argument("--judge", default=None)
    e.add_argument("--sim", default=None)
    li = sub.add_parser("lint")
    li.add_argument("--tools", default="v1")
    li.add_argument("--prompt", default="v1")
    m = sub.add_parser("mine")
    m.add_argument("--trace-dir", default=str(RUNS / "traces"))
    m.add_argument("--out", default="candidates.yaml")
    a = ap.parse_args()

    if a.cmd == "run":
        from agentlab.assistant import prompts
        from agentlab.costs import Budget
        from agentlab.evals.report import render_markdown
        from agentlab.evals.runner import run_eval
        from agentlab.evals.task import load_tasks
        from agentlab.llm.registry import get_model
        from shopfront.seed import build
        cfg = models_config().get("evals", {})
        tasks = load_tasks(a.suite, split=None if a.split == "all" else a.split,
                           tags=[t for t in a.tags.split(",") if t] or None)
        out = Path(a.out) if a.out else new_run_dir(RUNS / "evals")
        tmpl = out / "template.db"
        out.mkdir(parents=True, exist_ok=True)
        build(tmpl, out_dir=out / "seed_side_files")
        prompt = prompts.get_prompt(a.prompt)
        judge, sim = a.judge or cfg.get("judge"), a.sim or cfg.get("user_sim")
        import subprocess
        from agentlab.config import resolve
        try:
            git_sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        except OSError:
            git_sha = ""
        meta_extra = {"prompt": a.prompt, "split": a.split, "suite": a.suite, "git_sha": git_sha,
                      "resolved": {mm: ":".join(resolve(mm)) for mm in a.models.split(",")},
                      "judge": judge and ":".join(resolve(judge)), "user_sim": sim and ":".join(resolve(sim))}
        trials = run_eval(tasks, {mm: (lambda mm=mm: get_model(mm)) for mm in a.models.split(",")},
                          template_db=tmpl, trials=a.trials, budget=Budget(limit_usd=a.budget, label="evals"),
                          judge_factory=(lambda: get_model(judge)) if judge else None,
                          sim_factory=(lambda: get_model(sim)) if sim else None,
                          assistant_opts={"system_prompt": prompt, "tool_variant": a.tools}, out_dir=out,
                          meta_extra=meta_extra,
                          retry_provider_errors=a.retry_errors)
        md = render_markdown(trials, title=f"{Path(a.suite).name} ({a.split}) prompt={a.prompt}")
        (out / "report.md").write_text(md)
        print(md)
        print(f"results: {out}")
    elif a.cmd == "report":
        from agentlab.evals.report import render_markdown
        from agentlab.evals.runner import load_trials
        md = render_markdown(load_trials(Path(a.run_dir) / "trials.jsonl"), title=Path(a.run_dir).name, k=a.k)
        (Path(a.run_dir) / "report.md").write_text(md)
        print(md)
    elif a.cmd == "compare":
        from agentlab.evals.report import compare
        from agentlab.evals.runner import load_trials
        if len(a.runs) == 1:
            res = compare(load_trials(Path(a.runs[0]) / "trials.jsonl"), a.a, a.b)
            label = f"{a.b} - {a.a}"
        else:
            if not a.model:
                raise SystemExit("comparing two runs needs --model (compare the SAME model across runs)")
            ta = [t for t in load_trials(Path(a.runs[0]) / "trials.jsonl") if t.model == a.model]
            tb = [t for t in load_trials(Path(a.runs[1]) / "trials.jsonl") if t.model == a.model]
            for t in ta:
                t.model = "A"
            for t in tb:
                t.model = "B"
            res = compare(ta + tb, "A", "B")
            label = f"run B - run A (model {a.model})"
        print(f"{label}: diff {res['diff']*100:+.1f} pts, 95% CI [{res['lo']*100:+.1f}, {res['hi']*100:+.1f}] "
              f"over {res['tasks']} tasks" + ("  (CI includes 0: no demonstrated difference)" if res['lo'] <= 0 <= res['hi'] else ""))
    elif a.cmd == "experiment":
        import json as _json
        from agentlab.costs import Budget
        from agentlab.evals.experiment import Variant, append_log, run_experiment
        from agentlab.evals.task import load_tasks
        from agentlab.llm.registry import get_model
        from shopfront.seed import build

        import json as _j
        from agentlab.assistant.prompts import get_prompt
        from agentlab.assistant.tools import parse_variant

        def variant(spec: str) -> Variant:
            kv = {}
            for part in (p for p in spec.split(",") if p):
                if "=" not in part:
                    raise SystemExit(f"bad variant part {part!r}: use key=value, e.g. prompt=v2,tools=v1+desc,opt.effort=\"low\"")
                k, v = part.split("=", 1)
                if k not in ("prompt", "tools") and not k.startswith("opt."):
                    raise SystemExit(f"unknown variant key {k!r}: use prompt=, tools= or opt.<model option>=")
                kv[k] = v
            opts = {}
            for k, v in kv.items():
                if k.startswith("opt."):
                    try:
                        opts[k[4:]] = _j.loads(v)        # opt.parallel_tools=false -> False, opt.effort="low"
                    except ValueError:
                        opts[k[4:]] = v
            vv = Variant(spec, prompt=kv.get("prompt", "v1"), tools=kv.get("tools", "v1"), model_opts=opts)
            get_prompt(vv.prompt)          # fail fast, before building anything
            parse_variant(vv.tools)
            return vv
        cfg = models_config().get("evals", {})
        out = new_run_dir(RUNS / "experiments")
        out.mkdir(parents=True, exist_ok=True)
        tmpl = out / "template.db"
        build(tmpl, out_dir=out / "seed_side_files")
        tasks = load_tasks(a.suite, split=None if a.split == "all" else a.split,
                           tags=[t for t in a.tags.split(",") if t] or None)
        judge, sim = a.judge or cfg.get("judge"), a.sim or cfg.get("user_sim")
        vb, vc = variant(a.baseline), variant(a.candidate)
        import subprocess
        from agentlab.config import resolve
        sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        hashes = (vb.fingerprint(), vc.fingerprint())
        (out / "meta.json").write_text(_json.dumps({"model": ":".join(resolve(a.model)), "baseline": a.baseline,
                                                     "candidate": a.candidate, "hashes": hashes, "git_sha": sha,
                                                     "split": a.split, "tags": a.tags, "trials": a.trials}, indent=2))
        res = run_experiment(tasks, lambda: get_model(a.model), vb, vc,
                             template_db=tmpl, trials=a.trials, budget=Budget(limit_usd=a.budget, label="experiment"),
                             judge_factory=(lambda: get_model(judge)) if judge else None,
                             sim_factory=(lambda: get_model(sim)) if sim else None, margin=a.margin, out_dir=out)
        c = res.comparison
        print(f"candidate - baseline: {c['diff']*100:+.1f} pts [{c['lo']*100:+.1f}, {c['hi']*100:+.1f}] over "
              f"{c['tasks']} tasks -> {res.verdict}{' (PARTIAL: budget reached)' if res.partial else ''}")
        for split, sc in res.by_split.items():
            print(f"  split {split:8} {sc['diff']*100:+.1f} [{sc['lo']*100:+.1f}, {sc['hi']*100:+.1f}] "
                  f"over {sc['tasks']} tasks -> {sc['verdict']}")
        for tag, (x, y) in res.by_tag.items():
            print(f"  {tag:16} {'–' if x is None else f'{x:.0%}':>5} -> {'–' if y is None else f'{y:.0%}':>5}")
        log = Path(a.log) if Path(a.log).is_absolute() else ROOT / a.log
        append_log(log, hypothesis=a.hypothesis, change=a.change or a.candidate, model=a.model, result=res,
                   decision=a.decision, hashes=hashes)
        print(f"logged to {log}; trials in {out}")
    elif a.cmd == "lint":
        import sys as _sys
        from agentlab.assistant.prompts import get_prompt
        from agentlab.assistant.tools import make_support_tools
        from agentlab.tools.lint import lint_prompt, lint_tools
        from shopfront import db as _db
        conn = _db.connect()
        findings = lint_tools(make_support_tools(conn, 9001, variant=a.tools).specs()) + lint_prompt(get_prompt(a.prompt))
        for f in findings:
            print(f"{f.level:7} {f.where:28} {f.rule:22} {f.message}")
        print(f"{len(findings)} findings")
        _sys.exit(1 if any(f.level == "error" for f in findings) else 0)
    elif a.cmd == "mine":
        from agentlab.evals.flywheel import candidates_to_yaml, mine_traces
        cands = mine_traces(Path(a.trace_dir))
        Path(a.out).write_text(candidates_to_yaml(cands))
        print(f"{len(cands)} candidates -> {a.out}")


if __name__ == "__main__":
    main()
