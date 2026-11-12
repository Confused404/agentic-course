"""Course configuration: paths, .env loading, model aliases."""
from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
# traces, cost ledger, eval results (git-ignored). Tests point this at a temp dir (conftest.py).
RUNS = Path(os.environ.get("AGENTLAB_RUNS_DIR", ROOT / "runs"))


def new_run_dir(parent: Path) -> Path:
    """A fresh, never-reused run directory under `parent`: timestamp + microseconds + pid.
    why: one-second timestamps let two quick runs share a directory and silently mix their trials.jsonl."""
    from datetime import datetime
    parent.mkdir(parents=True, exist_ok=True)
    d = parent / f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-{os.getpid()}"
    d.mkdir(exist_ok=False)
    return d


@lru_cache
def models_config() -> dict:
    return tomllib.loads((ROOT / "config" / "models.toml").read_text())


MODES = ("free", "openrouter", "direct")


def models_mode() -> str:
    """Which alias table applies (config/models.toml explains them). Read from the environment on every call, so
    a .env change or a test's monkeypatch takes effect without restarting anything."""
    m = os.environ.get("COURSE_MODELS", "auto").strip().lower() or "auto"
    if m == "auto":
        return "direct" if os.environ.get("ANTHROPIC_API_KEY") else "free"
    if m not in MODES:
        raise ValueError(f"COURSE_MODELS={m!r}: use auto, {', '.join(MODES)}")
    return m


def aliases() -> dict[str, str]:
    """alias -> 'provider:model' for the current mode, with AGENTLAB_ALIAS_<NAME> overrides from the environment."""
    cfg = models_config()
    table = dict(cfg["aliases"])
    mode = models_mode()
    if mode == "free":
        table.update(cfg.get("aliases_free", {}))
    elif mode == "openrouter":
        table.update(cfg.get("aliases_openrouter", {}))
    for name in list(table):
        override = os.environ.get("AGENTLAB_ALIAS_" + name.upper().replace("-", "_"), "").strip()
        if override:
            table[name] = override
    return table


def resolve(alias_or_spec: str) -> tuple[str, str]:
    """'fast' -> ('anthropic', 'claude-haiku-5-5') in direct mode; 'ollama:qwen3:8b' -> ('ollama', 'qwen3:8b')."""
    spec = aliases().get(alias_or_spec, alias_or_spec)
    if ":" not in spec:
        raise ValueError(f"Unknown model alias or spec {alias_or_spec!r}. Use an alias from "
                         f"config/models.toml or 'provider:model'.")
    provider, model = spec.split(":", 1)
    if provider not in models_config().get("providers", {}):
        raise ValueError(f"Unknown provider {provider!r} in {spec!r} (alias {alias_or_spec!r})")
    return provider, model


def fallbacks_for(model: str) -> list[str]:
    """OpenRouter fallback model ids for a model id ([fallbacks] in config/models.toml), possibly empty."""
    return list(models_config().get("fallbacks", {}).get(model, []))


def is_free_model(provider: str, model: str) -> bool:
    return provider == "openrouter" and model.endswith(":free")


def provider_config(provider: str) -> dict:
    try:
        return models_config()["providers"][provider]
    except KeyError:
        raise ValueError(f"No [providers.{provider}] section in config/models.toml") from None


def api_key(provider: str) -> str | None:
    env = provider_config(provider).get("api_key_env")
    return os.environ.get(env) if env else "not-needed"


def course_budget_usd() -> float:
    """Default per-process spending cap. Override with COURSE_BUDGET_USD in .env."""
    return float(os.environ.get("COURSE_BUDGET_USD", "1.00"))
