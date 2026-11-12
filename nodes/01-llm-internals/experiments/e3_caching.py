"""E3: prompt caching. Same prefix twice (write, then read), then a one-character change (miss).

    .venv/bin/python nodes/01-llm-internals/experiments/e3_caching.py [--models fast,gpt-fast]
Cost: ~$0.01. Anthropic uses explicit cache_control and asks for a cache-miss diagnosis;
OpenAI-family models cache automatically above a minimum length and report cached_tokens.

Free OpenRouter models (the default without an Anthropic key) rarely report cache reads, so expect zeros there:
that's the "no explicit caching" baseline. The saving computation and the cache-miss diagnosis need an Anthropic key
(or a paid OpenAI-family model on OpenRouter, which caches automatically).

Caches live a few minutes. Re-running within ~5 minutes turns step 1 into a cache READ. Wait, or pass
--prefix-tokens with a different value to get a fresh prefix.
"""
import _common

from agentlab.probe import append_jsonl, build_haystack, print_table

args = _common.parse_args("fast,gpt-fast", 0.10, [(("--prefix-tokens",), {"type": int, "default": 12000})])
budget = _common.Budget(args.budget, "node01-e3")
out = _common.out_path("e3_caching.jsonl", True)
prefix = "You are Shopfront's support assistant. Reference:\n\n" + build_haystack(args.prefix_tokens, "(end)", 1.0)
changed = "X" + prefix[1:]        # one character different at the very start
assert changed != prefix
rows = []
with _common.run_span("node01-e3"):
    for alias, provider, model in _common.targets(args.models):
        prev_id = None
        for step, system in [("1 first call (expect write)", prefix), ("2 same prefix (expect read)", prefix),
                             ("3 first char changed (expect miss)", changed)]:
            kw = _common.quick(provider)
            if provider == "anthropic":
                sys_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
                # Every request opts in to diagnostics (the first with previous_message_id=None), so the API
                # stores a fingerprint to compare the next request against.
                kw["diagnostics"] = {"previous_message_id": prev_id}
                r = _common.call(provider, model, system=sys_blocks, user="Say OK.", budget=budget,
                                 experiment="e3", label=step, max_tokens=200, **kw)
            else:
                r = _common.call(provider, model, system=system, user="Say OK.", budget=budget, experiment="e3",
                                 label=step, max_tokens=200, **kw)
            prev_id = r.extra.get("message_id", prev_id)
            append_jsonl(out, r)
            rows.append({"model": alias, "step": step, "uncached_in": r.input_tokens,
                         "cache_write": r.cache_write_tokens, "cache_read": r.cache_read_tokens, "ttft_s": r.ttft_s,
                         "cost_usd": r.cost_usd, "diagnostics": str(r.extra.get("diagnostics", "-"))[:80],
                         "error": r.error or ""})
print_table(rows, title="E3 caching")
print("diagnostics: None = no divergence / first call; {'cache_miss_reason': None} = comparison pending; "
      "a reason type (e.g. system changed) = why step 3 missed.")
print(f"spent ${budget.spent_usd:.5f}")
