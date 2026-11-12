"""E1: the same text costs different numbers of tokens on different vendors.

    .venv/bin/python nodes/01-llm-internals/experiments/e1_tokens.py [--models fast,gpt-fast,local]
Cost: well under $0.01 (Anthropic counting is a free endpoint; others use max_tokens=1 calls).
"""
import json

import _common
import tiktoken

from agentlab.probe import ProbeResult, anthropic_count_tokens, append_jsonl, print_table

SAMPLES = {
    "english": "Your order shipped yesterday and should arrive within three to seven business days.",
    "json_schema": json.dumps(_common.NEUTRAL_TOOLS[1]["schema"]),
    "python": "def max_refundable_cents(order: dict) -> int:\n    return order['total_cents'] - sum(r['amount_cents'] for r in order['refunds'])",
    "french": "Votre commande a été expédiée hier et devrait arriver dans un délai de trois à sept jours ouvrables.",
    "japanese": "ご注文の商品は昨日発送されました。3〜7営業日以内に到着する予定です。",
    "order_ids": "Orders: 4821, 4822, 4823, 4824, 4825, 4826, 4827, 4828, 4829, 4830",
    "uuid": "toolu_01A9xQ3bK7vPz2mN8cR4tY6w f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "emoji": "Thanks!! 🎉🙏📦✅ Love it 😍",
}

args = _common.parse_args(_common.matrix_default(), 0.05)
budget = _common.Budget(args.budget, "node01-e1")
enc = tiktoken.get_encoding("o200k_base")   # an OpenAI-family tokenizer, offline
out = _common.OUT / "e1_tokens.jsonl"
rows = []
_run = _common.run_span("node01-e1")
_run.__enter__()
for name, text in SAMPLES.items():
    row = {"sample": name, "chars": len(text), "chars/4": len(text) // 4, "tiktoken_o200k": len(enc.encode(text))}
    for alias, provider, model in _common.targets(args.models):
        try:
            if provider == "anthropic":
                base = anthropic_count_tokens(model, system="", messages=[{"role": "user", "content": "x"}])
                n = anthropic_count_tokens(model, system="", messages=[{"role": "user", "content": text}]) - base + 1
            else:
                # max_tokens=16, not 1: some reasoning models reject or misbehave with tiny limits
                r0 = _common.call(provider, model, system="", user="x", budget=budget, experiment="e1",
                                  max_tokens=16, stream=False)
                r1 = _common.call(provider, model, system="", user=text, budget=budget, experiment="e1",
                                  max_tokens=16, stream=False)
                if r0.error or r1.error:   # the raw callers return errors as data; don't count them as tokens
                    raise RuntimeError((r0.error or r1.error)[:60])
                n = (r1.input_tokens + r1.cache_read_tokens) - (r0.input_tokens + r0.cache_read_tokens) + 1
        except Exception as e:  # noqa: BLE001
            n = f"err: {str(e)[:40]}"
        row[alias] = n
        append_jsonl(out, ProbeResult("e1", provider, model, label=name, extra={"tokens": n}))
    rows.append(row)
_run.__exit__(None, None, None)
print_table(rows, title="Tokens per sample (vendor counts; '+1' corrects for the 'x' baseline)")
print(f"spent ${budget.spent_usd:.5f}. Raw rows: {out}")
