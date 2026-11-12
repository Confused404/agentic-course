"""LIVE (Tier 2): `make eval N=04 BUDGET=3 MODELS=fast,gpt-fast,local`. Writes runs/evals/<ts>/ with report.md."""
import os
import time
from pathlib import Path

import pytest

from agentlab.config import RUNS, models_config
from agentlab.costs import Budget
from agentlab.evals.report import render_markdown
from agentlab.evals.runner import run_eval
from agentlab.evals.task import load_tasks
from agentlab.llm.registry import get_model

SUITE = Path(__file__).resolve().parents[1] / "evals" / "support"


@pytest.mark.live
def test_live_matrix(template_db):
    models = [m for m in (os.environ.get("EVAL_MODELS") or ",".join(models_config()["matrix"]["default"])).split(",") if m]
    cfg = models_config()["evals"]
    out = RUNS / "evals" / time.strftime("%Y%m%d-%H%M%S")
    trials = run_eval(load_tasks(SUITE, split="dev"), {m: (lambda m=m: get_model(m)) for m in models},
                      template_db=template_db, trials=int(os.environ.get("EVAL_TRIALS", "3")),
                      budget=Budget(label="node04-evals"), judge_factory=lambda: get_model(cfg["judge"]),
                      sim_factory=lambda: get_model(cfg["user_sim"]), out_dir=out)
    md = render_markdown(trials, title=f"Support suite (dev) {out.name}")
    (out / "report.md").write_text(md)
    print("\n" + md)
