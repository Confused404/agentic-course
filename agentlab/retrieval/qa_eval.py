"""Evaluating retrieval and answers (TEXTBOOK §6, §8).

Two levels, measured separately because they fail separately:
- retrieval_eval: did the retriever put the gold documents in the top k? No model calls: free and instant.
- run_qa: is the final answer right (graded), cited, and what did it cost? Results are Node 04 `Trial`s, so the
  Node 04 report, compare and stats work unchanged.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from agentlab.costs import Budget, BudgetExceeded
from agentlab.evals.graders import GradeResult, _norm
from agentlab.evals.runner import Trial, error_kind
from agentlab.llm.types import ChatModel
from agentlab.retrieval.index import KBIndex
from agentlab.retrieval.metrics import hit_at_k, ndcg_at_k, recall_at_k, reciprocal_rank
from agentlab.retrieval.qa import ABSTAIN, QAResult, answer

QA_GRADERS = {"answer_regex", "answer_not_regex", "abstains", "cites_any"}
TYPES = ("lookup", "identifier", "paraphrase", "stale", "multi_hop", "aggregate", "unanswerable")
# why a broad pattern as well as the exact phrase: models paraphrase the instruction; any clear "not in the KB"
# counts. A confident answer to an unanswerable question is the failure we're catching.
ABSTAIN_RX = re.compile(r"couldn'?t find|could not find|can'?t find|cannot find|"
                        r"not (in|covered in|listed|mentioned|specified|stated) (in |by )?(the |our )?"
                        r"(knowledge base|documents?|docs)|not (listed|mentioned|specified|stated)\b|"
                        r"no information|doesn'?t (say|mention|list|specify|include)|"
                        r"does not (say|mention|list|specify|include)|don'?t (have|sell|carry|offer|see)|"
                        r"do not (have|sell|carry|offer)|isn'?t (listed|mentioned|specified)", re.I)


@dataclass
class QATask:
    id: str
    question: str
    type: str
    gold: list[str] = field(default_factory=list)
    graders: list[dict] = field(default_factory=list)
    split: str = "dev"
    note: str = ""


def load_qa(path: str | Path, split: str | None = None, types: list[str] | None = None) -> list[QATask]:
    path = Path(path)
    files = sorted(path.glob("*.yaml")) if path.is_dir() else [path]
    tasks = [QATask(**raw) for f in files for raw in (yaml.safe_load(f.read_text()) or [])]
    for t in tasks:
        if t.type not in TYPES:
            raise ValueError(f"{t.id}: unknown type {t.type!r}")
        if not t.graders or any(g.get("type") not in QA_GRADERS for g in t.graders):
            raise ValueError(f"{t.id}: graders must be non-empty and one of {sorted(QA_GRADERS)}")
        if (t.type == "unanswerable") != (not t.gold):
            raise ValueError(f"{t.id}: unanswerable tasks (only) have empty gold")
    ids = [t.id for t in tasks]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate task ids")
    if split:
        tasks = [t for t in tasks if t.split == split]
    if types:
        tasks = [t for t in tasks if t.type in types]
    return tasks


def grade_answer(spec: dict, res: QAResult) -> GradeResult:
    t = spec["type"]
    a = _norm(res.answer)
    if t == "answer_regex":
        ok = re.search(spec["pattern"], a, re.I) is not None
        return GradeResult(t, "pass" if ok else "fail", "" if ok else f"/{spec['pattern']}/ not in {a[:160]!r}")
    if t == "answer_not_regex":
        m = re.search(spec["pattern"], a, re.I)
        return GradeResult(t, "fail" if m else "pass", f"forbidden {m.group(0)!r}" if m else "")
    if t == "abstains":
        ok = _norm(ABSTAIN) in a or ABSTAIN_RX.search(a) is not None
        return GradeResult(t, "pass" if ok else "fail", "" if ok else f"answered instead: {a[:160]!r}")
    if t == "cites_any":
        ok = bool(set(spec["docs"]) & set(res.cited))
        return GradeResult(t, "pass" if ok else "fail", "" if ok else f"cited {res.cited}")
    raise ValueError(f"unknown QA grader {t!r}")


def retrieval_eval(tasks: list[QATask], index: KBIndex, modes=("bm25", "hybrid"), k: int = 5,
                   include_archived: bool = False) -> dict:
    """Per mode: mean hit@k, recall@k, MRR, nDCG@k overall and by question type (answerable questions only)."""
    out = {}
    for mode in modes:
        rows = []
        for t in tasks:
            if not t.gold:
                continue
            ranked = index.rank_docs(t.question, k=max(k, 10), mode=mode, include_archived=include_archived)
            g = set(t.gold)
            rows.append({"id": t.id, "type": t.type, "ranked": ranked[:k], "hit": hit_at_k(ranked, g, k),
                         "recall": recall_at_k(ranked, g, k), "mrr": reciprocal_rank(ranked, g),
                         "ndcg": ndcg_at_k(ranked, g, k)})
        mean = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
        agg = lambda rs: {m: mean([r[m] for r in rs]) for m in ("hit", "recall", "mrr", "ndcg")}  # noqa: E731
        out[mode] = {"k": k, "overall": agg(rows),
                     "by_type": {ty: agg([r for r in rows if r["type"] == ty]) for ty in TYPES
                                 if any(r["type"] == ty for r in rows)},
                     "rows": rows}
    return out


def render_retrieval(res: dict) -> str:
    lines = []
    for mode, r in res.items():
        o = r["overall"]
        lines.append(f"## {mode} (k={r['k']}): hit {o['hit']:.2f} · recall {o['recall']:.2f} · MRR {o['mrr']:.2f} · "
                     f"nDCG {o['ndcg']:.2f}")
        lines.append("| type | hit | recall | MRR | nDCG |\n|---|---|---|---|---|")
        for ty, m in r["by_type"].items():
            lines.append(f"| {ty} | {m['hit']:.2f} | {m['recall']:.2f} | {m['mrr']:.2f} | {m['ndcg']:.2f} |")
        misses = [x for x in r["rows"] if x["hit"] == 0]
        if misses:
            lines.append("\nMissed entirely: " + ", ".join(x["id"] for x in misses))
        lines.append("")
    return "\n".join(lines)


def run_qa(tasks: list[QATask], model_factory: Callable[[], ChatModel], index: KBIndex, specs: list[str], *,
           trials: int = 1, budget: Budget | None = None, out_dir: Path | None = None) -> list[Trial]:
    """Every spec on every task, interleaved (trial, task, spec) so drift doesn't favour one mode. Trial.model is
    the spec, so `report.compare(trials, spec_a, spec_b)` is the paired comparison."""
    results: list[Trial] = []
    out_dir = Path(out_dir) if out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    for k in range(trials):
        for t in tasks:
            for spec in specs:
                t0 = time.perf_counter()
                spent0 = budget.spent_usd if budget else 0.0
                try:
                    res = answer(spec, t.question, index, model_factory(), budget=budget)
                    err, kind = res.error, ("agent" if res.error else None)
                except BudgetExceeded:
                    raise
                except Exception as e:  # noqa: BLE001
                    res = QAResult(spec, t.question, "", [], error=f"{type(e).__name__}: {e}")
                    err, kind = res.error, error_kind(e)
                grades = [grade_answer(g, res) for g in t.graders] if not err else []
                verdict = "error" if err else ("fail" if any(g.verdict == "fail" for g in grades) else "pass")
                g = set(t.gold)
                trial = Trial(t.id, k, spec, verdict, grades, [res.answer], list(res.tool_calls), [],
                              (budget.spent_usd - spent0) if budget else res.cost_usd,
                              time.perf_counter() - t0, res.calls, [], err, [t.type], t.split, kind, 0.0,
                              {"question": t.question, "cited": res.cited, "shown": res.retrieved[:20],
                               "shown_recall": recall_at_k(res.retrieved, g, len(res.retrieved) or 1) if g else None,
                               "cites_gold": (bool(g & set(res.cited)) if g else None),
                               "input_tokens": res.usage.total_input, "cache_read_tokens": res.usage.cache_read_tokens,
                               "output_tokens": res.usage.output_tokens})
                results.append(trial)
                print(f"[{k}] {t.id:24} {spec:18} {verdict:5} ${trial.cost_usd:.4f} {trial.latency_s:5.1f}s")
                if out_dir:
                    with open(out_dir / "trials.jsonl", "a") as f:
                        f.write(json.dumps(asdict(trial), default=str) + "\n")
    return results


def render_qa(trials: list[Trial]) -> str:
    """Accuracy, citation of gold, tokens, cost and latency per mode, plus accuracy by question type."""
    from collections import defaultdict
    by = defaultdict(list)
    for t in trials:
        by[t.model].append(t)
    types = [ty for ty in TYPES if any(ty in t.tags for t in trials)]
    head = ["mode", "acc", *types, "cites gold", "in tok/q", "$/q", "p50 s"]
    rows = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    pct = lambda xs: "–" if not xs else f"{sum(xs) / len(xs):.0%}"  # noqa: E731
    for mode, ts in by.items():
        # agent errors (an agentic answer that ran out of turns) count as fails, as in Node 04; only provider and
        # timeout errors are excluded: those say nothing about the mode
        ok = [t for t in ts if t.verdict in ("pass", "fail") or (t.verdict == "error" and t.error_kind == "agent")]
        lat = sorted(t.latency_s for t in ts)
        cg = [t.extra["cites_gold"] for t in ok if t.extra.get("cites_gold") is not None]
        rows.append("| " + " | ".join([
            mode, pct([t.verdict == "pass" for t in ok]),
            *[pct([t.verdict == "pass" for t in ok if ty in t.tags]) for ty in types],
            pct(cg), f"{sum(t.extra['input_tokens'] for t in ts) / len(ts):,.0f}",
            f"{sum(t.cost_usd for t in ts) / len(ts):.4f}", f"{lat[len(lat) // 2]:.1f}"]) + " |")
    errs = [t for t in trials if t.verdict == "error" and t.error_kind != "agent"]
    agent_errs = [t for t in trials if t.verdict == "error" and t.error_kind == "agent"]
    notes = (f"\n\n{len(errs)} provider/timeout errors (excluded from accuracy)." if errs else "") + (
        f"\n{len(agent_errs)} agent errors (counted as failures)." if agent_errs else "")
    return "\n".join(rows) + notes + "\n"
