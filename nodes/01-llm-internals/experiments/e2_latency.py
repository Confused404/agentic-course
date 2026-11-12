"""E2: latency = TTFT(prefill) + output/decode_speed. Vary input length and output length.

    .venv/bin/python nodes/01-llm-internals/experiments/e2_latency.py [--models fast,local] [--trials 2] [--fresh]
Cost: ~$0.02 on the default models.

Every call gets a unique nonce at the START of the prompt. Without it, the 2nd+ calls with the same
document would hit the provider's automatic prefix cache (or Ollama's KV reuse) and you'd be measuring
caching, not prefill. (Removing the nonce is a good E7.)
"""
import uuid

import _common

from agentlab.probe import append_jsonl, build_haystack, estimate_tokens, load_jsonl, print_table, summarize

args = _common.parse_args("fast,gpt-fast,local", 0.10,
                          [(("--lengths",), {"default": "1000,8000,32000"}),
                           (("--local-max",), {"type": int, "default": 3000,
                                               "help": "cap input length for local models (see APPENDIX: "
                                                       "Ollama's default context may be only 4096 tokens)"})])
budget = _common.Budget(args.budget, "node01-e2")
out = _common.out_path("e2_latency.jsonl", args.fresh)
lengths = [int(x) for x in args.lengths.split(",")]
trials = args.trials or 2
with _common.run_span("node01-e2"):
    for alias, provider, model in _common.targets(args.models):
        for L in lengths:
            if provider == "ollama" and L > args.local_max:
                print(f"skip {alias} len={L} (> --local-max {args.local_max})")
                continue
            doc = build_haystack(L, needle="(end of reference material)", position=1.0)
            for words in (40, 400):
                for t in range(trials):
                    system = f"[run {uuid.uuid4().hex}]\nReference material:\n\n" + doc
                    r = _common.call(provider, model, system=system,
                                     user=f"Ignoring the reference material, write about {words} words on why "
                                          f"tents need ventilation.",
                                     budget=budget, experiment="e2", label=f"in={L} out~{words}w",
                                     max_tokens=2000, **_common.quick(provider))
                    reported = r.input_tokens + r.cache_read_tokens + r.cache_write_tokens
                    r.params.update({"input_len": L, "target_words": words})
                    r.extra["truncated?"] = bool(reported and reported < 0.8 * estimate_tokens(system))
                    append_jsonl(out, r)
                    ttft = "None" if r.ttft_s is None else f"{r.ttft_s:.2f}s"
                    print(alias, r.label, "ERROR " + r.error if r.error else
                          f"ttft={ttft} total={r.total_s:.2f}s out={r.output_tokens} in={reported}"
                          + ("  << prompt shorter than sent: TRUNCATED?" if r.extra["truncated?"] else ""))
res = load_jsonl(out)
print_table(summarize(res, ["model", "label"], ["ttft_s", "extra.ttft_any_s", "total_s", "output_tokens",
                                               "output_tps", "cost_usd"]), title="E2 latency")
print(f"spent ${budget.spent_usd:.4f}")
