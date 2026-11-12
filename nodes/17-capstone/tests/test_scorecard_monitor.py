import json

import pytest


def test_window_metrics_and_alerts():
    from agentlab.launch.monitor import firing, window_metrics
    ev = [{"ts": 100 + i, "session": f"s{i // 2}", "error_kind": "provider" if i < 4 else None,
           "handover": i < 4, "latency_s": float(i), "cost_usd": 0.01} for i in range(20)]
    m = window_metrics(ev, now=119, window_s=600)
    assert m["conversations"] == 10 and m["turns"] == 20 and m["error_rate"] == 0.2
    assert m["p95_latency_s"] == 18.0 and m["cost_per_conversation"] == pytest.approx(0.02)
    cfg = {"min_conversations": 5, "error_rate_max": 0.1, "handover_rate_max": 0.5}
    assert [a.split()[0] for a in firing(m, cfg)] == ["error_rate"]
    assert firing(m, {**cfg, "min_conversations": 50}) == [], "too little traffic to tell"
    assert window_metrics(ev, now=10_000, window_s=60)["error_rate"] is None


def test_drill_alerts_fire_in_incidents_only(needs_assemble):
    import agentlab.launch.__main__ as cli
    import io
    import contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cli.main(["drill"]) == 0
    rows = [r for r in out.getvalue().splitlines() if r.startswith("| ") and r[2].isdigit()]
    by_phase = {}
    for r in rows:
        cells = [c.strip() for c in r.strip("|").split("|")]
        by_phase.setdefault(cells[1], []).append(cells[-1])
    assert not any(by_phase["normal"]), "no false alarms in normal traffic"
    assert any("error_rate" in a for a in by_phase["provider outage"])
    assert any("handover_rate" in a for a in by_phase["prompt regression: tool loop"])


def test_regression_rate_leaves_heldout_out(tmp_path, needs_assemble):
    from dataclasses import asdict
    from agentlab.evals.runner import Trial
    from agentlab.launch.scorecard import build_scorecard

    def T(i, verdict, split):
        return Trial(f"t{i}", 0, "fast", verdict, [], [], [], [], 0.0, 1.0, 1, ["end_turn"], None, [], split)
    d = tmp_path / "evals"
    d.mkdir()
    ts = [T(1, "pass", "dev"), T(2, "pass", "dev"), T(3, "fail", "heldout"), T(4, "fail", "heldout")]
    (d / "trials.jsonl").write_text("".join(json.dumps(asdict(t)) + "\n" for t in ts))
    card = build_scorecard(evals_dir=d)
    assert card["regression_pass_rate"]["value"] == 1.0 and card["heldout_pass_rate"]["value"] == 0.0


def test_scorecard_from_run_dirs(tmp_path):
    from agentlab.launch.scorecard import build_scorecard, measured_at
    from agentlab.reliability.chaos import ChaosResult
    from dataclasses import asdict
    d = tmp_path / "chaos"
    d.mkdir()
    rows = [ChaosResult("a", "durable", 0, completed=True, refund_ok=True, refunds=1),
            ChaosResult("a", "durable", 1, completed=False, refund_ok=True, refunds=1)]
    (d / "results.jsonl").write_text("\n".join(json.dumps(asdict(r)) for r in rows))
    card = build_scorecard(chaos_dir=d)
    assert card["chaos_completed"]["value"] == 0.5 and card["refunded_without_answer"]["value"] == 1
    assert card["chaos_completed"]["measured_at"].endswith("+00:00")
    (d / "meta.json").write_text(json.dumps({"started": "2026-11-20T10:00:00+00:00"}))
    assert measured_at(d) == "2026-11-20T10:00:00+00:00"
    with pytest.raises(ValueError):
        build_scorecard(chaos_dir=d, chaos_config="naive")


def test_cli_gate_and_validation(tmp_path):
    import agentlab.launch.__main__ as cli
    with pytest.raises(ValueError):
        cli.main(["scorecard"])
    with pytest.raises(ValueError):
        cli.main(["scorecard", "--perf", str(tmp_path / "nope")])
    card = tmp_path / "card.json"
    import datetime as dt
    today = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    card.write_text(json.dumps({"m": {"value": 1.0, "measured_at": today, "source": "x"}}))
    pol = tmp_path / "p.toml"
    pol.write_text('[[rules]]\nmetric = "m"\nop = ">="\nthreshold = 0.5\nseverity = "blocker"\n')
    try:
        assert cli.main(["gate", "--scorecard", str(card), "--policy", str(pol)]) == 0
        pol.write_text('[[rules]]\nmetric = "m"\nop = ">="\nthreshold = 2\nseverity = "blocker"\n')
        assert cli.main(["gate", "--scorecard", str(card), "--policy", str(pol)]) == 1
    except NotImplementedError:
        pytest.skip("needs your AGENT-OFF gate")
