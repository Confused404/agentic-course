"""E5: does position and length change recall, especially with near-duplicate distractors?

    .venv/bin/python nodes/01-llm-internals/experiments/e5_needle.py [--models fast,gpt-fast,local]
Cost: ~$0.05 on defaults. For local models, compare the prompt tokens Ollama REPORTS with the
estimate: if they're far lower, your prompt was silently truncated (TEXTBOOK §7).
"""
import _common

from agentlab.probe import append_jsonl, build_haystack, estimate_tokens, load_jsonl, print_table, summarize

args = _common.parse_args(_common.matrix_default(), 0.40, [(("--lengths",), {"default": "8000,30000"}),
                                                            (("--hard",), {"action": "store_true",
                                                             "help": "several dated versions; the model must pick the latest"})])
budget = _common.Budget(args.budget, "node01-e5")
out = _common.out_path("e5_needle.jsonl", args.fresh)
if not args.hard:
    NEEDLE = "Internal note: the loading-dock door code for the Halifax warehouse is 4471."
    DISTRACTORS = ["Internal note: the old loading-dock door code for the Halifax warehouse (retired in 2024) was 4417.",
                   "Internal note: the loading-dock door code for the Montreal warehouse is 7714."]
else:  # recall + comparison: the needle is just the most recent of several near-identical facts
    NEEDLE = "Security update 2026-09-14: Halifax loading-dock door code changed to 4471."
    DISTRACTORS = ["Security update 2026-02-03: Halifax loading-dock door code changed to 4417.",
                   "Security update 2026-06-21: Halifax loading-dock door code changed to 4174.",
                   "Security update 2026-10-02: Montreal loading-dock door code changed to 7714.",
                   "Security update 2025-12-11: Halifax loading-dock door code changed to 1447."]
Q = "What is the CURRENT loading-dock door code for the Halifax warehouse? Reply with just the 4 digits."
trials = args.trials or 2
tag = "hard " if args.hard else ""
with _common.run_span("node01-e5"):
    for alias, provider, model in _common.targets(args.models):
        for L in [int(x) for x in args.lengths.split(",")]:
            for pos in (0.0, 0.25, 0.5, 0.75, 1.0):
                hay = build_haystack(L, NEEDLE, pos, DISTRACTORS, seed=7)
                for t in range(trials):
                    # max_tokens is generous because reasoning tokens count against it (TEXTBOOK §6); a
                    # truncated reply must not be scored as a recall failure, so we track it separately
                    r = _common.call(provider, model, system="Answer from the document only.\n\n" + hay, user=Q,
                                     budget=budget, experiment="e5", label=f"{tag}len={L} pos={pos}",
                                     max_tokens=1000, stream=False, **_common.quick(provider))
                    r.extra.update({"correct": "4471" in r.text,
                                    "said_distractor": any(d in r.text for d in ("4417", "7714", "4174", "1447")),
                                    "truncated": r.stop_reason in ("length", "max_tokens"),
                                    "estimated_prompt_tokens": estimate_tokens(hay),
                                    "reported_prompt_tokens": r.input_tokens + r.cache_read_tokens + r.cache_write_tokens})
                    append_jsonl(out, r)
res = load_jsonl(out)
print_table(summarize(res, ["model", "label"], ["extra.correct", "extra.said_distractor", "extra.truncated",
                                                  "extra.reported_prompt_tokens", "extra.estimated_prompt_tokens"]),
            title="E5 needle recall by length and position")
print("If reported_prompt_tokens << estimated for a local model, the runtime truncated your prompt (APPENDIX).")
print(f"spent ${budget.spent_usd:.4f}")
