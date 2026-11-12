"""Probe results: one record per raw model call, plus summary statistics.

Why JSONL + a dataclass instead of a DataFrame: every record is appended as soon as it exists, so
a crash, a BudgetExceeded or a Ctrl-C mid-experiment loses nothing (see TEXTBOOK §4: you measure
rates over many noisy samples, so partial runs are still data).
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProbeResult:
    experiment: str
    provider: str
    model: str
    label: str = ""
    params: dict = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    ttft_s: float | None = None
    total_s: float = 0.0
    cost_usd: float | None = None
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    stop_reason: str = ""
    error: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def output_tps(self) -> float | None:
        # why: decode speed excludes prefill time, so subtract TTFT (TEXTBOOK §3 latency model)
        if self.ttft_s is None:
            return None
        decode_s = self.total_s - self.ttft_s
        return self.output_tokens / decode_s if decode_s > 0 else None


def append_jsonl(path: str | Path, result: ProbeResult) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(asdict(result), default=str) + "\n")


def load_jsonl(path: str | Path) -> list[ProbeResult]:
    path = Path(path)
    if not path.exists():
        return []
    return [ProbeResult(**json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


def _get(r: ProbeResult, key: str) -> Any:
    if key.startswith("params."):
        return r.params.get(key[7:])
    if key.startswith("extra."):
        return r.extra.get(key[6:])
    return getattr(r, key)


def _pct(sorted_vals: list[float], q: float) -> float:
    # nearest-rank percentile: the smallest value with at least q% of values <= it
    k = max(1, math.ceil(q / 100 * len(sorted_vals)))
    return sorted_vals[k - 1]


def summarize(results: list[ProbeResult], group_by: list[str], metrics: list[str]) -> list[dict]:
    groups: dict[tuple, list[ProbeResult]] = {}
    for r in results:   # dicts preserve insertion order -> first-seen group order
        groups.setdefault(tuple(_get(r, g) for g in group_by), []).append(r)
    rows = []
    for key, rs in groups.items():
        row: dict[str, Any] = dict(zip(group_by, key))
        row["n"] = len(rs)
        row["errors"] = sum(1 for r in rs if r.error)
        ok = [r for r in rs if not r.error]
        for m in metrics:
            vals = sorted(float(v) for v in (_get(r, m) for r in ok) if v is not None)
            if not vals:
                row.update({f"{m}_mean": None, f"{m}_std": None, f"{m}_p50": None, f"{m}_p90": None})
                continue
            row[f"{m}_mean"] = statistics.fmean(vals)
            row[f"{m}_std"] = statistics.stdev(vals) if len(vals) > 1 else 0.0
            row[f"{m}_p50"] = _pct(vals, 50)
            row[f"{m}_p90"] = _pct(vals, 90)
        rows.append(row)
    return rows


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.4g}"
    return "" if v is None else str(v)


def print_table(rows: list[dict], title: str = "") -> None:
    from rich.console import Console
    from rich.table import Table
    if not rows:
        print(f"{title}: (no rows)")
        return
    cols: list[str] = []
    for r in rows:
        cols += [c for c in r if c not in cols]
    t = Table(title=title)
    for c in cols:
        t.add_column(c)
    for r in rows:
        t.add_row(*[_fmt(r.get(c)) for c in cols])
    Console().print(t)
