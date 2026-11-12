import pytest

from agentlab.llm import fake


class Polite:
    provider, model = "fake", "claude-haiku-5-5"

    def complete(self, **kw):
        return fake.say("Thanks! Could you share your order number?")


def test_all_three_through_the_same_graders(seeded, tmp_path, needs_convert, needs_nodes):
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel
    from agentlab.config import ROOT
    from agentlab.evals.task import load_tasks
    from agentlab.frameworks import compare as C
    tasks = load_tasks(ROOT / "nodes/04-evals/evals/support/regression.yaml")[:2]
    pai = lambda: FunctionModel(lambda m, i: ModelResponse([TextPart("Thanks! Could you share your order number?")]),  # noqa: E731
                                model_name="claude-haiku-5-5")
    trials = C.run_compare(tasks, list(C.IMPLS), model_factory=Polite, alias="fast", template_db=seeded / "shop.db",
                           out_dir=tmp_path, pai_model_factory=pai)
    assert [t.model for t in trials] == list(C.IMPLS) * 2
    assert all(t.replies == ["Thanks! Could you share your order number?"] * len(t.replies) for t in trials)
    verdicts = {}
    for t in trials:
        verdicts.setdefault(t.task_id, set()).add(t.verdict)
    assert all(len(v) == 1 for v in verdicts.values()), "same behaviour -> same verdicts on every implementation"
    s = C.summarize(trials)
    assert set(s) == set(C.IMPLS) and all(x["code_lines"] > 0 for x in s.values())
    assert "| langgraph |" in C.render(s)
    assert len((tmp_path / "trials.jsonl").read_text().splitlines()) == 6


def test_runner_hook_is_backwards_compatible():
    import inspect
    from agentlab.evals.runner import run_trial
    assert inspect.signature(run_trial).parameters["assistant_factory"].default is None


def test_cli_fails_fast(tmp_path, monkeypatch):
    import agentlab.frameworks.__main__ as cli
    monkeypatch.setattr(cli, "RUNS", tmp_path)
    for bad in (["compare", "--model", "nosuchalias"], ["compare", "--model", "fast", "--impls", "crewai"],
                ["compare", "--model", "fast", "--trials", "0"]):
        with pytest.raises(ValueError):
            cli.main(bad)
    assert not (tmp_path / "frameworks").exists()
    assert cli.main(["graph-show", "nope"]) == 1
    with pytest.raises(ValueError):
        C_factory = __import__("agentlab.frameworks.compare", fromlist=["factory_for"]).factory_for
        C_factory("crewai", "fast")


def test_framework_provider_errors_are_infrastructure():
    from pydantic_ai.exceptions import FallbackExceptionGroup, ModelHTTPError
    from agentlab.evals.runner import error_kind
    e = ModelHTTPError(429, "m")
    assert error_kind(e) == "provider"
    assert error_kind(FallbackExceptionGroup("all failed", [e, ModelHTTPError(503, "m2")])) == "provider"
    assert error_kind(ValueError("bug")) == "agent"
