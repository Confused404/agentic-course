"""`make check-env`: what can this machine do? Prints a readiness report for the course.

Checks: Python, keys present (never prints them), which models each alias means right now (free or paid), your
OpenRouter account's free-model allowance, a live one-line call to each default model (skip with
`make check-env OFFLINE=1`), Ollama if you opted in, SQLite extensions, Docker, coding agents on PATH.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agentlab.config import (aliases, api_key, is_free_model, models_config, models_mode,  # noqa: E402
                             provider_config, resolve)
from agentlab.costs import price_for  # noqa: E402

OK, WARN, BAD = "\033[32m✔\033[0m", "\033[33m!\033[0m", "\033[31m✘\033[0m"
MODE_HELP = {
    "free": "free OpenRouter models only (no Anthropic key). $0, but rate-limited. Bought OpenRouter credits and "
            "want Claude/GPT through it? Put COURSE_MODELS=openrouter in .env",
    "openrouter": "everything through OpenRouter, paid (Claude via OpenRouter)",
    "direct": "Claude from Anthropic, other vendors via OpenRouter",
}


def line(mark: str, msg: str) -> None:
    print(f" {mark} {msg}")


def get_json(url: str, headers: dict | None = None, timeout: float = 10) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=timeout) as r:
        return json.load(r)


def price_label(provider: str, model: str) -> str:
    if is_free_model(provider, model) or provider == "ollama":
        return "free"
    p = price_for(model)
    return f"paid ${p['input']:g}/${p['output']:g} per 1M in/out" if p else "paid (price unknown: run make models)"


def openrouter_account() -> None:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return
    try:
        d = get_json("https://openrouter.ai/api/v1/key", {"Authorization": f"Bearer {key}"}).get("data", {})
    except Exception as e:  # noqa: BLE001
        line(WARN, f"OpenRouter key check failed ({type(e).__name__}: {e}); is the key right?")
        return
    free = d.get("free_model_daily_requests") or {}
    left = d.get("limit_remaining")
    line(OK, "OpenRouter key valid; " + ("never bought credits" if d.get("is_free_tier") else "has bought credits")
         + (f"; credit left on this key: ${left:.2f}" if isinstance(left, (int, float)) else ""))
    if free:
        line(OK if (free.get("remaining") or 0) > 20 else WARN,
             f"free-model requests today: {free.get('used')} used of {free.get('limit')} "
             "(resets 00:00 UTC; 20/minute always)")
    if d.get("is_free_tier"):
        print("     Tip: $10 of OpenRouter credits, bought once, raises the free-model limit from 50 to 1,000 "
              "requests a day; most nodes' eval runs need a few hundred.")


def live_test(alias: str) -> None:
    provider, model = resolve(alias)
    if not api_key(provider):
        line(WARN, f"live {alias}: skipped, no key for {provider}")
        return
    t0 = time.perf_counter()
    try:
        if provider == "anthropic":
            import anthropic
            r = anthropic.Anthropic(api_key=api_key(provider), max_retries=0).messages.create(
                model=model, max_tokens=16, messages=[{"role": "user", "content": "Reply with: ok"}])
            answered = r.model
        else:
            import openai
            extra = {"models": [model, *models_config().get("fallbacks", {}).get(model, [])]} \
                if provider == "openrouter" else {}
            r = openai.OpenAI(base_url=provider_config(provider)["base_url"], api_key=api_key(provider),
                              max_retries=0, timeout=60).chat.completions.create(
                model=model, max_tokens=256, messages=[{"role": "user", "content": "Reply with: ok"}],
                extra_body=extra or None)
            answered = r.model or model
        # OpenRouter names the model that actually answered; a different one means a fallback served it
        note = "" if answered.startswith(model.split(":")[0]) else f" (answered by fallback {answered})"
        line(OK, f"live {alias}: {provider}:{model} answered in {time.perf_counter() - t0:.1f}s{note}")
    except Exception as e:  # noqa: BLE001
        msg = str(e).splitlines()[0][:160]
        hint = ""
        if "402" in msg:
            hint = " -> no credits for a paid model: buy credits, or remove COURSE_MODELS to use free models"
        elif "429" in msg:
            hint = " -> rate-limited (free models: 20/minute, daily cap); try again later"
        elif "404" in msg:
            hint = " -> model id gone? run make models"
        line(BAD, f"live {alias}: {provider}:{model} FAILED: {type(e).__name__}: {msg}{hint}")


def main() -> None:
    offline = os.environ.get("OFFLINE") or "--offline" in sys.argv
    print("Agentic course environment check\n")
    line(OK if sys.version_info >= (3, 12) else BAD, f"Python {platform.python_version()} (need >= 3.12)")
    has_or, has_an = bool(os.environ.get("OPENROUTER_API_KEY")), bool(os.environ.get("ANTHROPIC_API_KEY"))
    line(OK if has_or else BAD, f"OPENROUTER_API_KEY {'set' if has_or else 'missing: the only key the course needs'}")
    line(OK, f"ANTHROPIC_API_KEY {'set' if has_an else 'not set (optional: Claude direct)'}")
    budget = os.environ.get("COURSE_BUDGET_USD", "1.00 (default)")
    line(OK, f"COURSE_BUDGET_USD = {budget}")

    try:
        mode = models_mode()
    except ValueError as e:
        line(BAD, str(e))
        return
    print(f"\nModels: mode '{mode}' ({MODE_HELP[mode]})")
    table = aliases()
    for alias in table:
        provider, model = resolve(alias)
        print(f"   {alias:12} {provider}:{model:42} {price_label(provider, model)}")
    print()
    openrouter_account()
    if offline:
        line(WARN, "live calls skipped (OFFLINE)")
    else:
        print("   live test: one short call per default model (free models use 1 of your daily requests each)")
        seen = set()
        for alias in models_config()["matrix"]["default"]:
            if resolve(alias) not in seen:
                seen.add(resolve(alias))
                live_test(alias)

    if any(v.startswith("ollama:") for k, v in table.items() if k != "ollama"):
        local = resolve("local")[1] if table["local"].startswith("ollama:") else table["ollama"].split(":", 1)[1]
        try:
            with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as r:
                tags = [m["name"] for m in json.load(r).get("models", [])]
            has = any(t.startswith(local) for t in tags)
            line(OK if has else WARN,
                 f"Ollama running; '{local}' {'pulled' if has else 'NOT pulled: ollama pull ' + local}")
        except Exception:
            line(BAD, "an alias points at Ollama but it isn't reachable on :11434 (`ollama serve`)")
    else:
        line(OK, "Ollama not used (opt in on a machine with 16 GB+ RAM: AGENTLAB_ALIAS_LOCAL=ollama:qwen3:8b)")

    import sqlite3
    try:     # actually load it: some builds have the method but refuse extensions at runtime
        import sqlite_vec
        c = sqlite3.connect(":memory:")
        c.enable_load_extension(True)
        sqlite_vec.load(c)
        can_load = True
    except Exception:  # noqa: BLE001
        can_load = False
    line(OK if can_load else WARN, "SQLite extensions " + ("loadable (sqlite-vec works)" if can_load else
         "NOT loadable in this Python build: Node 07 dense search needs a python.org/Homebrew/uv Python"))
    docker = shutil.which("docker")
    ok = docker and subprocess.run(["docker", "info"], capture_output=True).returncode == 0
    line(OK if ok else WARN, "Docker daemon " + ("running" if ok else "not available (Node 03 sandbox falls back to a weaker local mode)"))
    for tool in ("claude", "opencode", "git", "gh"):
        line(OK if shutil.which(tool) else WARN, f"{tool} {'found' if shutil.which(tool) else 'not on PATH'}")
    print("\nWarnings are fine for now; each node says what it needs.")


if __name__ == "__main__":
    main()
