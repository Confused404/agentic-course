"""One change, measured: baseline vs candidate on the same tasks, interleaved, paired (TEXTBOOK §1, §6).

Verdicts: better (CI of the paired diff > 0) · worse (CI < 0) · non-inferior (CI > -margin: "didn't break it", the
question a regression check asks) · inconclusive · insufficient (fewer than MIN_TASKS tasks: a bootstrap over 1-7 tasks
gives intervals too narrow to trust).
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from agentlab.assistant.prompts import get_prompt
from agentlab.costs import Budget, BudgetExceeded
from agentlab.evals.report import compare, summarize
from agentlab.evals.runner import Trial, run_trial
from agentlab.evals.task import Task
from agentlab.llm.types import ChatModel

MIN_TASKS = 8


@dataclass
class Variant:
    name: str
    prompt: str = "v1"
    tools: str = "v1"
    model_opts: dict = field(default_factory=dict)

    def assistant_opts(self) -> dict:
        return {"system_prompt": get_prompt(self.prompt), "tool_variant": self.tools, "model_opts": dict(self.model_opts)}

    def fingerprint(self) -> str:
        """Content hash of what this variant actually sends: prompt text + tool specs + opts. Names are mutable;
        hashes aren't, so the log says what was really tested (TEXTBOOK §6, versioning)."""
        from agentlab.assistant.tools import make_support_tools
        from shopfront import db
        conn = db.connect(":memory:")
        db.init_schema(conn)
        specs = [s.__dict__ for s in make_support_tools(conn, 0, variant=self.tools).specs()]
        blob = json.dumps({"prompt": get_prompt(self.prompt), "tools": specs, "opts": self.model_opts}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:8]


@dataclass
class ExperimentResult:
    baseline: list[Trial]
    candidate: list[Trial]
    comparison: dict
    by_tag: dict[str, tuple[float | None, float | None]]
    verdict: str
    by_split: dict[str, dict] = field(default_factory=dict)
    partial: bool = False
    margin: float = 0.05


def _verdict(c: dict, margin: float) -> str:
    if c["tasks"] < MIN_TASKS:
        return "insufficient"
    if c["lo"] > 0:
        return "better"
    if c["hi"] < 0:
        return "worse"
    if c["lo"] > -margin:
        return "non-inferior"
    return "inconclusive"


def run_experiment(tasks: list[Task], model_factory: Callable[[], ChatModel], baseline: Variant, candidate: Variant, *,
                   template_db: Path, trials: int = 3, budget: Budget | None = None, judge_factory=None,
                   sim_factory=None, margin: float = 0.05, out_dir: Path | None = None) -> ExperimentResult:
    base, cand = [], []
    partial = False
    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
    try:
        for k in range(trials):
            for i, task in enumerate(tasks):
                # alternate which variant goes first, so caching/latency drift doesn't systematically favour one
                order = [("baseline", baseline, base), ("candidate", candidate, cand)]
                if (k + i) % 2:
                    order.reverse()
                pair = []
                for label, v, _ in order:
                    pair.append((label, run_trial(task, model_factory(), template_db=template_db, trial=k,
                                                  model_label=label, budget=budget, judge_factory=judge_factory,
                                                  sim_factory=sim_factory, assistant_opts=v.assistant_opts())))
                for label, t in pair:      # only complete pairs are kept (a budget stop mid-pair drops the half)
                    (base if label == "baseline" else cand).append(t)
                    print(f"[{k}] {task.id:24} {label:9} {t.verdict}")
                    if out_dir:
                        with open(Path(out_dir) / "trials.jsonl", "a") as f:
                            f.write(json.dumps(asdict(t), default=str) + "\n")
    except BudgetExceeded as e:
        partial = True
        print(f"! budget reached ({e}); analysing the {len(base)} complete pairs so far")
    if not base:
        raise RuntimeError("no complete baseline/candidate pairs: raise the budget")
    cmp_ = compare(base + cand, "baseline", "candidate")
    s = summarize(base + cand)
    tags = sorted({t for tr in base + cand for t in tr.tags})
    by_tag = {t: (s["baseline"]["by_tag"].get(t), s["candidate"]["by_tag"].get(t)) for t in tags}
    by_split = {}
    for split in sorted({t.split for t in base}):
        sub = [t for t in base + cand if t.split == split]
        try:
            c = compare(sub, "baseline", "candidate")
            by_split[split] = dict(c, verdict=_verdict(c, margin))
        except ValueError:
            pass
    return ExperimentResult(base, cand, cmp_, by_tag, _verdict(cmp_, margin), by_split, partial, margin)


HEADER = ("| date | model | change | hypothesis | baseline [hash] | candidate [hash] | tasks × trials | diff [lo, hi] | "
          "verdict | decision |\n|---|---|---|---|---|---|---|---|---|---|\n")


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def append_log(path: Path, *, hypothesis: str, change: str, model: str, result: ExperimentResult, decision: str = "",
               hashes: tuple[str, str] = ("", "")) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# Experiment log\n\n" + HEADER)
    s = summarize(result.baseline + result.candidate)
    pct = lambda x: "–" if x is None else f"{x * 100:.0f}%"  # noqa: E731
    c = result.comparison
    n_trials = max((t.trial for t in result.baseline), default=-1) + 1
    verdict = result.verdict + (" (partial)" if result.partial else "")
    row = (f"| {time.strftime('%Y-%m-%d %H:%M')} | {_cell(model)} | {_cell(change)} | {_cell(hypothesis)} | "
           f"{pct(s['baseline']['task_mean'])} [{hashes[0]}] | {pct(s['candidate']['task_mean'])} [{hashes[1]}] | "
           f"{c['tasks']} × {n_trials} | {c['diff'] * 100:+.0f} [{c['lo'] * 100:+.0f}, {c['hi'] * 100:+.0f}] | "
           f"{verdict} | {_cell(decision)} |\n")
    with open(path, "a") as f:
        f.write(row)
