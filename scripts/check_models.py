"""`make models`: verify every alias in config/models.toml points at a model that exists, and
refresh OpenRouter prices into runs/openrouter_prices.json.

Why this exists: model IDs and prices change monthly. Rather than trusting the course text,
ask the providers. (Anthropic: /v1/models. OpenRouter: /api/v1/models, which includes prices.)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agentlab.config import RUNS, api_key, models_config  # noqa: E402


def get_json(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def main() -> None:
    cfg = models_config()
    # every model any mode can use: the three alias tables plus the fallback lists
    entries: list[tuple[str, str]] = []
    for table in ("aliases", "aliases_free", "aliases_openrouter"):
        entries += [(f"{table}.{a}", spec) for a, spec in cfg.get(table, {}).items()]
    for primary, fbs in cfg.get("fallbacks", {}).items():
        entries += [(f"fallback of {primary.split('/')[-1]}", f"openrouter:{m}") for m in fbs]
    available: dict[str, set[str]] = {}
    try:
        key = api_key("anthropic")
        if key:
            data = get_json("https://api.anthropic.com/v1/models?limit=100",
                            {"x-api-key": key, "anthropic-version": "2023-06-01"})
            available["anthropic"] = {m["id"] for m in data["data"]}
    except Exception as e:
        print("anthropic: could not list models:", e)
    try:
        data = get_json("https://openrouter.ai/api/v1/models")
        available["openrouter"] = {m["id"] for m in data["data"]}
        prices = {}
        for m in data["data"]:
            p = m.get("pricing") or {}
            try:
                prices[m["id"]] = {"input": float(p.get("prompt", 0)) * 1e6,
                                   "output": float(p.get("completion", 0)) * 1e6,
                                   "cache_read": float(p.get("input_cache_read", p.get("prompt", 0))) * 1e6,
                                   "cache_write": float(p.get("input_cache_write", p.get("prompt", 0))) * 1e6}
            except (TypeError, ValueError):
                continue
        RUNS.mkdir(exist_ok=True)
        (RUNS / "openrouter_prices.json").write_text(json.dumps(prices, indent=1))
        print(f"openrouter: {len(prices)} model prices cached to runs/openrouter_prices.json")
    except Exception as e:
        print("openrouter: could not list models:", e)
    try:
        data = get_json("http://localhost:11434/api/tags")
        available["ollama"] = {m["name"] for m in data.get("models", [])}
    except Exception:
        print("ollama: not reachable (fine if you are not using local models yet)")

    print()
    for label, spec in dict.fromkeys(entries):
        provider, model = spec.split(":", 1)
        have = available.get(provider)
        if have is None:
            print(f"  ?  {label:28} {spec}  (could not check)")
        elif model in have or any(h.startswith(model) for h in have):
            print(f"  ✔  {label:28} {spec}")
        else:
            stem = model.split("/")[-1].split("-")[0]
            near = sorted(h for h in have if stem in h and h.endswith(":free") == model.endswith(":free"))[:6]
            print(f"  ✘  {label:28} {spec}  NOT FOUND. Similar: {near}")
    print("\nFix any ✘ by editing config/models.toml (or override one alias in .env: AGENTLAB_ALIAS_FAST=...).\n"
          "Free models rotate: pick replacements that support tools: openrouter.ai/models?max_price=0&supported_parameters=tools")


if __name__ == "__main__":
    main()
