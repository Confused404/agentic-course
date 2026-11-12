"""Root test configuration: tests must never write to your real runs/ (cost ledger, traces)."""
import pytest


@pytest.fixture(autouse=True)
def _isolated_runs_dir(tmp_path, monkeypatch):
    import agentlab.config as cfg
    runs = tmp_path / "runs"
    monkeypatch.setenv("AGENTLAB_RUNS_DIR", str(runs))
    monkeypatch.setattr(cfg, "RUNS", runs)
    yield
