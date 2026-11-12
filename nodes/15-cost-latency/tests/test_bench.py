import json
import math

import pytest

from agentlab.llm import fake
from agentlab.perf import bench as B


class Polite:
    """Always answers politely, never calls tools. Priced like Haiku so costs are non-zero."""
    def __init__(self, provider="anthropic", model="claude-haiku-5-5"):
        self.provider, self.model = provider, model

    def complete(self, **kw):
        return fake.say("Thanks for reaching out! Let me know your order number.")


def test_parse_config():
    c = B.parse_config("fast>mid+cache:auto+effort:low+nosticky")
    assert (c.cheap, c.strong, c.cache, c.effort, c.sticky) == ("fast", "mid", "auto", "low", False)
    assert B.parse_config("mid").aliases == ["mid"] and B.parse_config("fast>mid").aliases == ["fast", "mid"]
    for bad in ("", "openrouter:x", "fast>", ">mid", "a>b>c", "mid+cache:sometimes", "mid+effort:max",
                "mid+nosticky", "mid+turbo"):
        with pytest.raises(ValueError):
            B.parse_config(bad)


def test_bench_end_to_end(seeded, tmp_path, needs_economics, needs_prefix):
    from agentlab.evals.task import load_tasks
    from agentlab.config import ROOT
    tasks = load_tasks(ROOT / "nodes/04-evals/evals/support/regression.yaml")[:2]
    models = {"fast": lambda: Polite(), "mid": lambda: Polite(model="claude-sonnet-5-5")}
    trials = B.run_bench(tasks, ["mid", "fast>mid+cache:auto"], template_db=seeded / "shop.db",
                         get_model=lambda a: models[a](), out_dir=tmp_path,
                         price_as={"fast": "claude-opus-5-5", "mid": "claude-opus-5-5"})
    assert len(trials) == 4 and all(t.extra["calls"] for t in trials)
    assert all(r["label"] in ("fast", "mid") for t in trials for r in t.extra["calls"])
    assert all(t.extra["shadow_cost"] > t.extra["recorded_cost"] > 0 for t in trials), "Opus prices > Haiku/Sonnet"
    s = B.summarize(trials, human_cost_usd=5.0)
    assert set(s) == {"mid", "fast>mid+cache:auto"} and s["mid"].shadow
    assert s["fast>mid+cache:auto"].escalation_rate == 0.0 and s["mid"].escalation_rate is None
    md = B.render(s, human_cost_usd=5.0)
    assert "SHADOW" in md and "| mid |" in md
    lines = (tmp_path / "trials.jsonl").read_text().splitlines()
    assert len(lines) == 4 and json.loads(lines[0])["extra"]["calls"]


class Refunds(Polite):
    """Cheap model that always wants to refund: every call escalates (a high-stakes tool)."""
    def complete(self, **kw):
        r = fake.call("issue_refund", order_id=4822, amount_cents=100, reason="changed_mind")
        r.tool_calls[0].id = f"c{id(kw) % 10**6}"
        return r


def test_wiring_records_discarded_calls_charges_them_and_sees_the_layout(seeded, tmp_path, needs_economics,
                                                                         needs_prefix):
    from agentlab.costs import Budget
    from agentlab.config import ROOT
    from agentlab.evals.task import load_tasks
    task = load_tasks(ROOT / "nodes/04-evals/evals/support/regression.yaml")[:1]
    models = {"fast": lambda: Refunds(), "mid": lambda: Polite(model="claude-sonnet-5-5")}
    b = Budget(limit_usd=5.0)
    (t,) = B.run_bench(task, ["fast>mid+cache:timestamp+nosticky"], template_db=seeded / "shop.db",
                       get_model=lambda a: models[a](), budget=b)
    labels = [r["label"] for r in t.extra["calls"]]
    assert labels.count("fast") >= 1 and labels.count("mid") >= 1, "both models' calls recorded"
    assert t.extra["escalations"] == labels.count("fast"), "every cheap answer was discarded and recorded"
    assert b.calls == len(labels), "discarded cheap answers are charged too"
    assert all(r["request"]["system"].startswith("Current time") for r in t.extra["calls"]), \
        "the recorder sees the request AFTER the cache layout"


def test_pareto():
    def S(rate, cost):
        return B.ConfigSummary("x", {"n": 5, "resolution_rate": rate, "blended_cost": cost}, False, 1, 1,
                               {"read_share": None}, None)
    s = {"a": S(0.8, 1.0), "b": S(0.9, 2.0), "c": S(0.7, 1.5), "d": S(0.8, 1.0)}
    assert sorted(B.pareto(s)) == ["a", "b", "d"]


def test_breakeven_and_cli(tmp_path, monkeypatch):
    import agentlab.perf.__main__ as cli
    r = cli.selfhost_breakeven(1.0, 1000, 1.0, 0.5)
    assert r["selfhost_usd_per_mtok"] == pytest.approx(1e6 / 3.6e6) and r["breakeven_utilization"] == \
        pytest.approx((1e6 / 3.6e6) / 0.5)
    with pytest.raises(ValueError):
        cli.selfhost_breakeven(1.0, 0, 0.5)
    assert not math.isnan(cli.selfhost_breakeven(0.0, 10, 0.1)["selfhost_usd_per_mtok"])
    monkeypatch.setattr(cli, "RUNS", tmp_path)
    for bad in (["bench", "--configs", "nosuchalias"], ["bench", "--configs", "mid+turbo"],
                ["bench", "--configs", "mid", "--trials", "0"], ["bench", "--configs", "mid", "--price-as", "x"],
                ["bench", "--configs", "mid", "--price-as", "mid=claude-sonnet-5.5"],
                ["bench", "--configs", "fast>mid", "--price-as", "mid=claude-sonnet-5-5"],
                ["bench", "--configs", "mid", "--price-as", "fast=claude-haiku-5-5"]):
        with pytest.raises(ValueError):
            cli.main(bad)
    assert not (tmp_path / "perf").exists(), "nothing created before validation passes"
    monkeypatch.setenv("COURSE_MODELS", "free")
    assert cli.parse_price_as("auto", ["fast", "mid"]) == {"fast": "claude-haiku-5-5", "mid": "claude-sonnet-5-5"}
    monkeypatch.setenv("COURSE_MODELS", "direct")
    assert cli.parse_price_as("auto", ["fast"]) is None
    assert cli.parse_price_as("fast=claude-haiku-5-5,mid=claude-sonnet-5-5", ["fast", "mid"]) == \
        {"fast": "claude-haiku-5-5", "mid": "claude-sonnet-5-5"}
