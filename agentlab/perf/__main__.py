"""python -m agentlab.perf bench | report | doctor | breakeven   (Node 15 SPEC §4)

  bench     --configs mid,fast,fast>mid,... [--suite PATHS] [--tags T] [--trials 1] [--budget 2.0]
            [--price-as auto|none|ALIAS=MODEL_ID,...] [--human-cost 4.0]
  report    RUN_DIR [--human-cost 4.0]
  doctor    RUN_DIR [--config SPEC] [--task ID]       why each call did (not) hit the cache (free)
  breakeven --gpu-usd-per-hour 1.20 --tokens-per-second 900 [--utilization 0.3] [--api-usd-per-mtok 0.40]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentlab.config import ROOT, RUNS, models_config, models_mode, new_run_dir, resolve

SUITES = "nodes/04-evals/evals/support/regression.yaml,nodes/04-evals/evals/support/capability.yaml"
DEFAULT_CONFIGS = "mid,fast,fast>mid,mid+cache:auto,fast>mid+cache:auto"
# free mode: fast and mid are the same free model, so quality is identical; shadow prices (keyed by alias) still
# price fast as Haiku and mid as Sonnet, which is what the cost questions need
FREE_CONFIGS = "mid,fast,fast>mid,fast+cache:auto,fast+cache:timestamp"


def parse_price_as(spec: str, aliases: list[str]) -> dict[str, str] | None:
    """auto: in free mode, price each alias as the paid model it stands for ([aliases] in config/models.toml);
    otherwise none. ALIAS=MODEL_ID,...: explicit. none: real costs."""
    if spec == "none":
        return None
    if spec == "auto":
        if models_mode() != "free":
            return None
        paid = models_config()["aliases"]
        return {a: paid[a].split(":", 1)[1] for a in aliases if a in paid}
    from agentlab.costs import price_for
    out = {}
    for part in spec.split(","):
        a, _, m = part.partition("=")
        a, m = a.strip(), m.strip()
        if not a or not m:
            raise ValueError(f"--price-as {spec!r}: use auto, none or ALIAS=MODEL_ID,...")
        if aliases and a not in aliases:
            raise ValueError(f"--price-as: {a!r} isn't used by these configurations ({', '.join(aliases)})")
        if price_for(m) is None:
            raise ValueError(f"--price-as: no price for {m!r} in config/models.toml (a typo? `make models`)")
        out[a] = m
    missing = [a for a in aliases if a not in out]
    if aliases and missing:
        raise ValueError(f"--price-as: also give a price for {', '.join(missing)} (or every cost mixes real and "
                         "shadow prices)")
    return out


def selfhost_breakeven(gpu_usd_per_hour: float, tokens_per_second: float, utilization: float,
                       api_usd_per_mtok: float | None = None) -> dict:
    """Self-hosting cost per million tokens: you pay for the GPU-hour whether it's busy or not (TEXTBOOK §6)."""
    if gpu_usd_per_hour < 0 or tokens_per_second <= 0 or not 0 < utilization <= 1:
        raise ValueError("need gpu_usd_per_hour >= 0, tokens_per_second > 0, 0 < utilization <= 1")
    per_mtok = gpu_usd_per_hour / (tokens_per_second * 3600 * utilization) * 1e6
    out = {"selfhost_usd_per_mtok": per_mtok}
    if api_usd_per_mtok:
        # the utilization at which the GPU costs the same per token as the API
        out["breakeven_utilization"] = gpu_usd_per_hour / (tokens_per_second * 3600) * 1e6 / api_usd_per_mtok
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m agentlab.perf")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bench")
    b.add_argument("--configs", default=None, help=f"default: {DEFAULT_CONFIGS} (free mode: {FREE_CONFIGS})")
    b.add_argument("--suite", default=SUITES)
    b.add_argument("--tags", default="")
    b.add_argument("--trials", type=int, default=1)
    b.add_argument("--budget", type=float, default=3.0)
    b.add_argument("--price-as", default="auto")
    b.add_argument("--human-cost", type=float, default=4.0)
    r = sub.add_parser("report")
    r.add_argument("run_dir")
    r.add_argument("--human-cost", type=float, default=4.0)
    d = sub.add_parser("doctor")
    d.add_argument("run_dir")
    d.add_argument("--config")
    d.add_argument("--task")
    be = sub.add_parser("breakeven")
    be.add_argument("--gpu-usd-per-hour", type=float, required=True)
    be.add_argument("--tokens-per-second", type=float, required=True)
    be.add_argument("--utilization", type=float, default=0.3)
    be.add_argument("--api-usd-per-mtok", type=float)
    a = p.parse_args(argv)

    if a.cmd == "breakeven":
        res = selfhost_breakeven(a.gpu_usd_per_hour, a.tokens_per_second, a.utilization, a.api_usd_per_mtok)
        print(f"self-hosted: ${res['selfhost_usd_per_mtok']:.3f} per 1M tokens at {a.utilization:.0%} utilization")
        if "breakeven_utilization" in res:
            u = res["breakeven_utilization"]
            print(f"break-even with the API (${a.api_usd_per_mtok}/1M) at {u:.0%} utilization"
                  + ("  (above 100%: this GPU can't beat the API on price)" if u > 1 else ""))
        return 0

    from agentlab.evals.runner import load_trials
    from agentlab.perf.bench import parse_config, render, summarize
    if a.cmd == "report":
        trials = load_trials(Path(a.run_dir) / "trials.jsonl")
        md = render(summarize(trials, human_cost_usd=a.human_cost), human_cost_usd=a.human_cost)
        (Path(a.run_dir) / "report.md").write_text(md)
        print(md)
        return 0
    if a.cmd == "doctor":
        from agentlab.perf.caching import diagnose
        trials = load_trials(Path(a.run_dir) / "trials.jsonl")
        shown = 0
        for t in trials:
            if (a.config and t.model != a.config) or (a.task and t.task_id != a.task):
                continue
            print(f"\n## {t.task_id} [{t.model}] trial {t.trial}")
            for row in diagnose(t.extra.get("calls", [])):
                share = "–" if row["read_share"] is None else f"{row['read_share']:.0%}"
                print(f"  #{row['seq']:<2} {row['model'][:28]:28} prompt {row['prompt_tokens']:>6} "
                      f"cached {share:>4}  {row['why']}")
            shown += 1
            if shown >= 5 and not (a.config or a.task):
                print("\n(first 5 conversations; narrow with --config / --task)")
                break
        return 0

    # bench: validate everything before spending anything
    free = models_mode() == "free"
    configs = [c for c in (a.configs or (FREE_CONFIGS if free else DEFAULT_CONFIGS)).split(",") if c.strip()]
    parsed = [parse_config(c) for c in configs]
    aliases = sorted({al for c in parsed for al in c.aliases})
    for al in aliases:
        resolve(al)
    if a.trials < 1 or a.budget <= 0 or a.human_cost < 0:
        raise ValueError("--trials >= 1, --budget > 0, --human-cost >= 0")
    price_as = parse_price_as(a.price_as, aliases)
    from agentlab.costs import Budget
    from agentlab.evals.task import load_tasks
    from agentlab.llm.registry import get_model
    from agentlab.perf.bench import run_bench
    from shopfront.seed import build
    tasks = []
    for path in a.suite.split(","):
        tasks += load_tasks(ROOT / path.strip() if not Path(path.strip()).is_absolute() else path.strip(),
                            tags=[t for t in a.tags.split(",") if t] or None)
    if not tasks:
        raise ValueError("no tasks selected")
    out = new_run_dir(RUNS / "perf")
    build(out / "template.db", out_dir=out / "seed_side_files")
    ev = models_config().get("evals", {})
    (out / "meta.json").write_text(json.dumps({
        "configs": configs, "resolved": {al: ":".join(resolve(al)) for al in aliases}, "mode": models_mode(),
        "price_as": price_as, "trials": a.trials, "tasks": [t.id for t in tasks]}, indent=2))
    budget = Budget(limit_usd=a.budget, label="perf")
    judge, sim = ev.get("judge"), ev.get("user_sim")
    try:
        trials = run_bench(tasks, configs, template_db=out / "template.db", get_model=get_model, trials=a.trials,
                           budget=budget, judge_factory=(lambda: get_model(judge)) if judge else None,
                           sim_factory=(lambda: get_model(sim)) if sim else None, price_as=price_as, out_dir=out)
    except Exception as e:  # noqa: BLE001 - report what finished
        print(f"! stopped early: {type(e).__name__}: {e}")
        trials = load_trials(out / "trials.jsonl")
    md = render(summarize(trials, human_cost_usd=a.human_cost), human_cost_usd=a.human_cost)
    reported = sum(t.cost_usd + t.overhead_usd for t in trials)
    if budget.spent_usd - reported > 1e-6:
        md += (f"\n${budget.spent_usd - reported:.4f} of spend isn't in the table: the trial that hit the budget was "
               "paid for but never written (raise --budget to finish the run).\n")
    (out / "report.md").write_text(md)
    print(md + f"\nresults: {out}  (spent ${budget.spent_usd:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
