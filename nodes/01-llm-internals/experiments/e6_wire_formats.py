"""E6: look at the actual JSON each vendor sends back for the same tool-calling request.

    .venv/bin/python nodes/01-llm-internals/experiments/e6_wire_formats.py
Writes runs/node01/wire/<alias>-{single,parallel}.json. Open them side by side. Cost: < $0.01.
"""
import _common

from agentlab.probe import print_table

args = _common.parse_args(_common.matrix_default(), 0.05)
budget = _common.Budget(args.budget, "node01-e6")
wire = _common.OUT / "wire"
SYSTEM = "You are Shopfront's support assistant. Use tools. If several lookups are needed, do them in parallel."
rows = []
_run = _common.run_span("node01-e6")
_run.__enter__()
for alias, provider, model in _common.targets(args.models):
    for name, user in [("single", "Where is order 4824?"), ("parallel", "Compare orders 4821 and 4822 for me.")]:
        r = _common.call(provider, model, system=SYSTEM, user=user, budget=budget, experiment="e6", label=name,
                         tools_anthropic=_common.tools_for_anthropic(), tools_openai=_common.tools_for_openai(),
                         max_tokens=1500, stream=False, save_raw=wire / f"{alias}-{name}.json")
        rows.append({"model": alias, "case": name, "stop": r.stop_reason, "raw_stop": r.extra.get("raw_stop_reason"),
                     "n_tool_calls": len(r.tool_calls),
                     "calls": "; ".join(f"{c['name']}({c['raw_arguments'] or c['arguments']})" for c in r.tool_calls),
                     "parse_errors": sum(1 for c in r.tool_calls if c["parse_error"]), "text": r.text[:60],
                     "error": r.error or ""})
_run.__exit__(None, None, None)
print_table(rows, title="E6 wire formats (open runs/node01/wire/*.json)")
