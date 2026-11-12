"""Print a trace as a tree: `make trace` (latest) or `python scripts/trace_view.py <trace_id|path>`.

Reading traces is a core skill in this course. A trace answers "what did the agent actually do,
in what order, at what cost?" without trusting the agent's own summary of what it did.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from rich.console import Console
from rich.tree import Tree

import os
TRACES = Path(os.environ.get("AGENTLAB_RUNS_DIR", Path(__file__).resolve().parent.parent / "runs")) / "traces"


def load(arg: str | None) -> list[dict]:
    if arg and Path(arg).exists():
        path = Path(arg)
    elif arg:
        path = TRACES / f"{arg}.jsonl"
    else:
        files = sorted(TRACES.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        if not files:
            sys.exit("No traces yet in runs/traces/. Run an agent first.")
        path = files[-1]
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def label(s: dict, full: bool) -> str:
    a = s["attributes"]
    ms = (s["end"] - s["start"]) / 1e6
    bits = [f"[bold]{s['name']}[/bold]", f"{ms:.0f} ms"]
    if "gen_ai.usage.input_tokens" in a:
        bits.append(f"in={a['gen_ai.usage.input_tokens']} out={a['gen_ai.usage.output_tokens']}"
                    f" cache_r={a.get('gen_ai.usage.cache_read.input_tokens', 0)}"
                    f" cache_w={a.get('gen_ai.usage.cache_creation.input_tokens', 0)}")
    if "course.cost_usd" in a:
        bits.append(f"${a['course.cost_usd']:.5f}")
    if a.get("course.tool.is_error"):
        bits.append("[red]ERROR[/red]")
    if s["status"] == "ERROR":
        bits.append("[red]span error[/red]")
    out = "  ".join(bits)
    n = None if full else 300
    for key in ("course.tool.arguments", "course.tool.result", "course.content"):
        if key in a:
            out += f"\n    [dim]{key.split('.')[-1]}:[/dim] {str(a[key])[:n]}"
    return out


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    full = "--full" in sys.argv
    spans = sorted(load(args[0] if args else None), key=lambda s: s["start"])
    by_parent: dict[str | None, list[dict]] = {}
    ids = {s["span_id"] for s in spans}
    for s in spans:
        parent = s["parent_id"] if s["parent_id"] in ids else None
        by_parent.setdefault(parent, []).append(s)

    def add(node: Tree, s: dict) -> None:
        child = node.add(label(s, full))
        for c in by_parent.get(s["span_id"], []):
            add(child, c)

    root = Tree(f"trace {spans[0]['trace_id']}  ({len(spans)} spans)")
    for s in by_parent.get(None, []):
        add(root, s)
    total = sum(s["attributes"].get("course.cost_usd", 0) for s in spans)
    Console().print(root)
    Console().print(f"Total model cost: ${total:.5f}")


if __name__ == "__main__":
    main()
