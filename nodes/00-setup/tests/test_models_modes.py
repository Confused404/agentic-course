"""Node 00 grader: the model aliases work with zero configuration (offline; no keys needed)."""
import pytest

from agentlab import config
from agentlab.costs import compute_cost
from agentlab.llm.types import Usage


@pytest.fixture()
def env(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "COURSE_MODELS"):
        monkeypatch.delenv(k, raising=False)
    for k in list(__import__("os").environ):
        if k.startswith("AGENTLAB_ALIAS_"):
            monkeypatch.delenv(k)
    return monkeypatch


def test_only_an_openrouter_key_means_free_models(env):
    env.setenv("OPENROUTER_API_KEY", "x")
    assert config.models_mode() == "free"
    for alias in ("fast", "mid", "top", "gpt-fast", "gpt-mid", "local", "open-hosted"):
        provider, model = config.resolve(alias)
        assert provider == "openrouter" and model.endswith(":free"), alias
    vendors = {config.resolve(a)[1].split("/")[0] for a in config.models_config()["matrix"]["default"]}
    assert len(vendors) == 3, "the default comparison still compares three vendors"
    judge, graded = config.resolve(config.models_config()["evals"]["judge"]), config.resolve("fast")
    assert judge[1].split("/")[0] != graded[1].split("/")[0], "judge from another vendor"


def test_anthropic_key_means_direct(env):
    env.setenv("ANTHROPIC_API_KEY", "x")
    assert config.models_mode() == "direct" and config.resolve("fast") == ("anthropic", "claude-haiku-5-5")


def test_openrouter_mode_routes_claude_through_openrouter(env):
    env.setenv("COURSE_MODELS", "openrouter")
    assert config.resolve("fast") == ("openrouter", "anthropic/claude-haiku-5.5")
    usage = Usage(input_tokens=1000, output_tokens=100)
    assert compute_cost("anthropic/claude-haiku-5.5", usage) == compute_cost("claude-haiku-5-5", usage)


def test_overrides_and_bad_modes(env):
    env.setenv("AGENTLAB_ALIAS_GPT_FAST", "ollama:qwen3:8b")
    assert config.resolve("gpt-fast") == ("ollama", "qwen3:8b")
    env.setenv("COURSE_MODELS", "cheap")
    with pytest.raises(ValueError):
        config.models_mode()


def test_free_models_cost_nothing_and_have_fallbacks(env):
    env.setenv("OPENROUTER_API_KEY", "x")
    _, model = config.resolve("fast")
    assert compute_cost(model, Usage(input_tokens=10**6, output_tokens=10**6)) == 0.0
    fb = config.fallbacks_for(model)
    assert fb and all(m.endswith(":free") and m != model for m in fb)


def test_free_models_are_paced_and_get_fallbacks():
    from agentlab.llm import pacing
    from agentlab.llm.fake import ScriptedModel, say
    t, slept = [0.0], []

    def sleep(s):
        slept.append(s)
        t[0] += s
    pacing._STAMPS.clear()
    inner = ScriptedModel([say("x")] * 5)
    seen = []
    orig = inner.complete
    inner.complete = lambda **kw: (seen.append(kw), orig(**kw))[1]
    m = pacing.FreeTierPacer(pacing.WithDefaults(inner, fallback_models=["b:free"]), rpm=2,
                             clock=lambda: t[0], sleep=sleep)
    for _ in range(3):
        m.complete(system="", messages=[])
    assert slept and t[0] >= 60.0, "the third call in a minute waits"
    assert seen[0]["fallback_models"] == ["b:free"] and m.provider == inner.provider
    pacing._STAMPS.clear()
