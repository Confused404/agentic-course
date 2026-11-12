"""E5: measure an OpenAI-compatible endpoint (your self-hosted model, or any provider for comparison).

    .venv/bin/python electives/E5-self-hosting/bench_endpoint.py --base-url http://localhost:11434/v1 \
        --model qwen3:4b [--api-key-env LLM_API_KEY] [--runs 5]

Reports: time to first token and output tokens/second (streamed, ~512-token answers), prompt reading speed at 2k
and 8k tokens of input, tool-call validity on a few Shopfront-style prompts, and errors. The API key is read from the
environment variable you name, never from the command line (shell history).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time

TOOLS = [{"type": "function", "function": {
    "name": "lookup_order", "description": "Get an order's status by its numeric id.",
    "parameters": {"type": "object", "properties": {"order_id": {"type": "integer"}}, "required": ["order_id"]}}},
    {"type": "function", "function": {
        "name": "search_help_center", "description": "Search the help center articles.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}]
TOOL_PROMPTS = [("Where is my order 4822?", "lookup_order", {"order_id": 4822}),
                ("What's your return policy for opened items?", "search_help_center", None),
                ("Has order 4821 shipped yet?", "lookup_order", {"order_id": 4821}),
                ("How do I reset my password?", "search_help_center", None)]


def stream_once(client, model: str, prompt: str, max_tokens: int) -> dict:
    t0 = time.perf_counter()
    first, n_chunks, text = None, 0, []
    s = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}],
                                       max_tokens=max_tokens, stream=True,
                                       stream_options={"include_usage": True})
    usage = None
    for ch in s:
        if ch.choices and ch.choices[0].delta and ch.choices[0].delta.content:
            if first is None:
                first = time.perf_counter() - t0
            n_chunks += 1
            text.append(ch.choices[0].delta.content)
        if getattr(ch, "usage", None):
            usage = ch.usage
    total = time.perf_counter() - t0
    out_tokens = usage.completion_tokens if usage else max(1, len("".join(text)) // 4)
    in_tokens = usage.prompt_tokens if usage else None
    gen_time = max(1e-6, total - (first or total))
    return {"ttft_s": first, "total_s": total, "out_tokens": out_tokens, "in_tokens": in_tokens,
            "decode_tps": out_tokens / gen_time if first else None}


def tool_check(client, model: str) -> list[dict]:
    rows = []
    for prompt, want, args in TOOL_PROMPTS:
        r = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], tools=TOOLS,
                                           max_tokens=512)
        calls = r.choices[0].message.tool_calls or []
        name = calls[0].function.name if calls else None
        try:
            parsed = json.loads(calls[0].function.arguments) if calls else None
            valid = isinstance(parsed, dict)
        except (TypeError, ValueError):
            parsed, valid = None, False
        rows.append({"prompt": prompt, "called": name, "right_tool": name == want, "json_ok": valid,
                     "args_ok": args is None or parsed == args})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--api-key-env", default="")
    ap.add_argument("--runs", type=int, default=3)
    a = ap.parse_args()
    import openai
    key = os.environ.get(a.api_key_env, "") if a.api_key_env else "none"
    if a.api_key_env and not key:
        raise SystemExit(f"environment variable {a.api_key_env} is empty")
    client = openai.OpenAI(base_url=a.base_url, api_key=key or "none", max_retries=0, timeout=600)
    errors = 0
    gen = []
    for _ in range(a.runs):
        try:
            gen.append(stream_once(client, a.model, "Write a detailed 400-word guide to packing a tent.", 512))
        except Exception as e:  # noqa: BLE001
            errors += 1
            print("error:", type(e).__name__, str(e)[:120])
    if gen:
        print(f"TTFT p50 {statistics.median(g['ttft_s'] for g in gen if g['ttft_s'] is not None):.2f}s  "
              f"decode {statistics.median(g['decode_tps'] for g in gen if g['decode_tps']):.1f} tok/s  "
              f"(first run includes any cold start: {gen[0]['ttft_s']:.2f}s)")
    filler = "The customer wrote about an order. " * 60          # ~ 500 tokens per repeat
    for reps in (4, 16):
        try:
            r = stream_once(client, a.model, filler * reps + "\nSummarise in one sentence.", 32)
            if r["in_tokens"] and r["ttft_s"]:
                print(f"prompt {r['in_tokens']} tokens: TTFT {r['ttft_s']:.2f}s -> prefill ~{r['in_tokens'] / r['ttft_s']:.0f} tok/s")
            else:
                print(f"prompt x{reps}: TTFT {r['ttft_s']}, usage not reported")
        except Exception as e:  # noqa: BLE001
            errors += 1
            print(f"prompt x{reps}: error {type(e).__name__}: {str(e)[:120]} (context too small?)")
    try:
        rows = tool_check(client, a.model)
        ok = sum(r["right_tool"] and r["json_ok"] and r["args_ok"] for r in rows)
        print(f"tool calls: {ok}/{len(rows)} fully right")
        for r in rows:
            print(f"  {r['prompt'][:40]:40} -> {r['called']} json_ok={r['json_ok']} args_ok={r['args_ok']}")
    except Exception as e:  # noqa: BLE001
        errors += 1
        print("tool check error:", type(e).__name__, str(e)[:160])
    print(f"errors: {errors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
