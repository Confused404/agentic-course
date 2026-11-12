"""E4: randomness and effort. (A) temperature vs diversity and tool-call accuracy on OpenAI-compatible
models; (B) effort vs accuracy/cost on an Anthropic model using a structured output.

    .venv/bin/python nodes/01-llm-internals/experiments/e4_sampling.py [--trials 10]
Cost: ~$0.05 on defaults.
"""
import json
from pathlib import Path

import _common

from agentlab.probe import append_jsonl, load_jsonl, print_table, summarize

args = _common.parse_args("gpt-fast,local", 0.25, [(("--anthropic",), {"default": "fast"})])
budget = _common.Budget(args.budget, "node01-e4")
out = _common.out_path("e4_sampling.jsonl", args.fresh)
_run = _common.run_span("node01-e4")
_run.__enter__()
N = args.trials or 10
SYSTEM = "You are Shopfront's support assistant. Use tools to answer. Today is 2026-11-01."
USER = "hi, my order 4821 arrived broken a while back. what are my options?"


def correct_first_call(r) -> bool:
    if not r.tool_calls or r.tool_calls[0]["arguments"] is None:
        return False
    c = r.tool_calls[0]
    a = c["arguments"]
    if c["name"] == "lookup_order":
        return a.get("order_id") == 4821
    if c["name"] == "refund_eligibility":
        return a.get("order_id") == 4821 and a.get("reason") == "damaged"
    return False


# ---- (A) temperature sweep (providers that still accept temperature)
for alias, provider, model in _common.targets(args.models):
    if provider == "anthropic":
        print("skip", alias, "in part A: current Claude models don't accept temperature (see appendix)")
        continue
    # An endpoint that ACCEPTS a parameter may not HONOUR it (reasoning models often ignore temperature, and
    # routers may drop unsupported params silently). On OpenRouter, require_parameters makes it route only to
    # hosts that support temperature, or fail loudly, which is itself a finding.
    extra = {"extra_body": {"provider": {"require_parameters": True}}} if provider == "openrouter" else {}
    for T in (0.0, 0.7, 1.3):
        for t in range(N):
            r = _common.call(provider, model, system=SYSTEM, user=USER, budget=budget, experiment="e4A",
                             label=f"T={T}", tools_openai=_common.tools_for_openai(), max_tokens=1500,
                             stream=False, temperature=T, **extra)
            r.extra["correct"] = correct_first_call(r)
            # why: json.dumps([]) == "[]" is truthy, so text-only replies need their own signature
            r.extra["signature"] = (json.dumps([(c["name"], c["arguments"]) for c in r.tool_calls])
                                    if r.tool_calls else "TEXT:" + r.text[:60])
            append_jsonl(out, r)
res = [r for r in load_jsonl(out) if r.experiment == "e4A"]
rows = []
for g in summarize(res, ["model", "label"], ["extra.correct", "output_tokens"]):
    sigs = {r.extra.get("signature") for r in res if r.model == g["model"] and r.label == g["label"] and not r.error}
    g["distinct_outputs"] = len(sigs)
    rows.append(g)
print_table(rows, title="E4-A temperature: accuracy of first tool call and output diversity")

# ---- (B) effort sweep with structured output (Anthropic)
policy = (Path(_common.OUT).parents[1] / "data" / "help_center" / "refund-policy.md").read_text()
schema = {"type": "object", "additionalProperties": False,
          "properties": {"eligible": {"type": "boolean"}, "window_days": {"type": "integer"},
                         "reason_code": {"type": "string", "enum": ["damaged", "changed_mind", "other"]}},
          "required": ["eligible", "window_days", "reason_code"]}
Q = ("Policy:\n" + policy + "\n\nCase: standard-tier customer, order delivered 45 days ago, says the "
     "item arrived broken (they only just unpacked it). Is a refund allowed under policy? Which window applies?")
for alias, provider, model in _common.targets(args.anthropic):
    if provider != "anthropic":
        # why skip: output_config (effort + JSON-schema output) is Anthropic's request shape; in free mode `fast` is
        # an OpenRouter model. Read the APPENDIX and the solution branch's notes instead, or rerun with an Anthropic key.
        print(f"skip E4-B for {alias} ({provider}:{model}): the effort sweep uses Anthropic's output_config; "
              "it needs ANTHROPIC_API_KEY (see README)")
        continue
    for effort in ("low", "medium", "high"):
        for t in range(max(3, N // 2)):
            r = _common.call(provider, model, system="Answer strictly per policy.", user=Q, budget=budget,
                             experiment="e4B", label=f"effort={effort}", max_tokens=4000,
                             output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}})
            r.extra["truncated"] = r.stop_reason == "max_tokens"   # constrained JSON is only valid if it finished
            try:
                ans = json.loads(r.text)
                r.extra["correct"] = ans["eligible"] is True and ans["window_days"] == 60
            except Exception:  # noqa: BLE001
                r.extra["correct"] = False
            append_jsonl(out, r)
res = [r for r in load_jsonl(out) if r.experiment == "e4B"]
print_table(summarize(res, ["model", "label"], ["extra.correct", "output_tokens", "reasoning_tokens", "total_s",
                                                  "cost_usd"]),
            title="E4-B effort vs correctness (structured output)")
_run.__exit__(None, None, None)
print(f"spent ${budget.spent_usd:.4f}")
