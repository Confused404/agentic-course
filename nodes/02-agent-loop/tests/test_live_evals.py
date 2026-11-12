"""LIVE: run the 10 cases against real models. `make eval N=02 BUDGET=1 MODELS=fast,gpt-fast,local`"""
import os
from pathlib import Path

import pytest

from agentlab.costs import Budget
from agentlab.evals.mini import load_cases, run_suite, summarize
from agentlab.llm.registry import get_model

CASES = Path(__file__).resolve().parents[1] / "evals" / "cases.yaml"


@pytest.mark.live
def test_live_suite(template_db):
    models = [m for m in (os.environ.get("EVAL_MODELS") or "fast").split(",") if m]
    budget = Budget(label="node02-evals")           # cap from COURSE_BUDGET_USD (make eval BUDGET=...)
    print()
    for alias in models:
        results = run_suite(load_cases(CASES), lambda: get_model(alias), template_db=template_db, budget=budget)
        s = summarize(results)
        print(f"{alias:12} pass {s['passed']}/{s['cases']}  cost ${s['cost_usd']:.4f}")
        for r in results:
            if not r.passed:
                print(f"   FAIL {r.case_id}: " + ", ".join(k for k, v in r.checks.items() if not v) + (f" error={r.error}" if r.error else ""))
    print(f"total spent ${budget.spent_usd:.4f}")
