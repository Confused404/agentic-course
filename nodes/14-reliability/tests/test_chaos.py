import pytest

from agentlab.reliability import chaos as C

S = {s.id: s for s in C.SCENARIOS}


def test_naive_loses_runs_retry_and_durable_dont(conn, refunder, needs_retry, needs_recovery, seeded, tmp_path):
    from shopfront import db
    out = {}
    for cfg in ("naive", "retry", "durable"):
        c = db.connect(db.snapshot(seeded / "shop.db", tmp_path / f"{cfg}.db"))
        out[cfg] = C.run_one(S["changed_mind"], cfg, refunder(4822), c, fault_rate=0.5, crash_rate=0.0, seed=3,
                             sleep=lambda s: None)
        c.close()
    assert out["naive"].injected and not out["naive"].completed, "the first provider error ends a naive run"
    assert out["retry"].completed and out["retry"].retries > 0
    assert out["durable"].completed and out["durable"].refund_ok


def test_crashes_durable_reconciles(refunder, needs_retry, needs_recovery, seeded, tmp_path):
    """Statistical on purpose: it must hold for any reasonable crash RNG, not just one seeding formula."""
    from shopfront import db
    lost, done = 0, 0
    for seed in range(6):
        for cfg in ("naive", "durable"):
            c = db.connect(db.snapshot(seeded / "shop.db", tmp_path / f"{cfg}{seed}.db"))
            r = C.run_one(S["changed_mind"], cfg, refunder(4822), c, fault_rate=0.0,
                          crash_rate=0.35 if cfg == "naive" else 0.2, seed=seed, sleep=lambda s: None)
            c.close()
            if cfg == "naive":
                lost += not r.completed
                continue
            assert r.refunds <= 1 and r.duplicate_attempts == 0, f"seed {seed}: never a second refund attempt"
            if r.completed:
                done += 1
                assert r.refund_ok, f"seed {seed}: finished with exactly one refund"
            else:
                assert r.resumes >= C.MAX_RESUMES, f"seed {seed}: lost before using its resumes ({r.error})"
    assert lost >= 1, "crashes lose naive runs"
    assert done >= 5, "durable runs survive crashes"


def test_requeue_reruns_from_the_top(refunder, needs_retry, seeded, tmp_path):
    from shopfront import db
    reruns = 0
    for seed in range(6):
        c = db.connect(db.snapshot(seeded / "shop.db", tmp_path / f"rq{seed}.db"))
        r = C.run_one(S["changed_mind"], "requeue", refunder(4822), c, fault_rate=0.0, crash_rate=0.35, seed=seed,
                      sleep=lambda s: None)
        c.close()
        reruns += r.resumes
        assert r.refunds <= 1, "the shop's one-refund-per-order rule holds even when a job reruns"
    assert reruns >= 1


def test_summary_and_render():
    assert C.CONFIGS == ("naive", "retry", "requeue", "durable")
    rs = [C.ChaosResult("a", "naive", 0, completed=False, refund_ok=True, refunds=1, crashes=1),
          C.ChaosResult("a", "durable", 0, completed=True, refund_ok=True, refunds=1, resumes=1)]
    s = C.summarize(rs)
    assert s["naive"]["silent"] == 1 and s["durable"]["completed"] == 1.0
    assert "refunded but no answer" in C.render(rs)


def test_cli_fails_fast(tmp_path, monkeypatch):
    import agentlab.reliability.__main__ as cli
    monkeypatch.setattr(cli, "RUNS", tmp_path)
    for bad in (["chaos", "--model", "fast", "--configs", "nope"], ["chaos", "--model", "nosuchalias"]):
        with pytest.raises(ValueError):
            cli.main(bad)
    assert not (tmp_path / "reliability").exists()
