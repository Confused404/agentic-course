"""python -m agentlab.retrieval index | search | eval-retrieval | qa | report   (Node 07 SPEC §6)

  index          [--embedder hash|fastembed[:model]] [--max-chars 1200] [--overlap 150]
  search  QUERY  [--mode bm25|dense|hybrid] [-k 5] [--archived] [--embedder ...]
  eval-retrieval --suite PATH [--modes bm25,dense,hybrid] [-k 5] [--split dev] [--embedder ...] [--archived]
  qa             --suite PATH --model ALIAS --modes rag:hybrid:5,agentic,longctx [--trials 1] [--budget 1]
                 [--split dev] [--types a,b] [--embedder ...]
  report         RUN_DIR [--a SPEC --b SPEC]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from agentlab.config import RUNS, new_run_dir
from agentlab.retrieval.corpus import load_corpus


def open_index(embedder: str | None, max_chars: int = 1200, overlap: int = 150):
    from agentlab.retrieval.embed import get_embedder
    from agentlab.retrieval.index import KBIndex
    emb = get_embedder(embedder) if embedder and embedder != "none" else None
    name = (emb.name if emb else "bm25").replace("/", "_").replace(":", "_")
    path = RUNS / "kb" / f"index-{name}-{max_chars}-{overlap}.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    idx = KBIndex(path, emb).build(load_corpus(), max_chars=max_chars, overlap_chars=overlap)
    return idx, time.perf_counter() - t0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m agentlab.retrieval")
    sub = p.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--embedder", default="hash", help="none | hash | fastembed[:model] (default: hash)")
    common.add_argument("--max-chars", type=int, default=1200)
    common.add_argument("--overlap", type=int, default=150)
    sub.add_parser("index", parents=[common])
    s = sub.add_parser("search", parents=[common])
    s.add_argument("query")
    s.add_argument("--mode", default="hybrid")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("--archived", action="store_true")
    e = sub.add_parser("eval-retrieval", parents=[common])
    e.add_argument("--suite", required=True)
    e.add_argument("--modes", default="bm25,dense,hybrid")
    e.add_argument("-k", type=int, default=5)
    e.add_argument("--split", default="dev")
    e.add_argument("--archived", action="store_true")
    q = sub.add_parser("qa", parents=[common])
    q.add_argument("--suite", required=True)
    q.add_argument("--model", required=True)
    q.add_argument("--modes", required=True)
    q.add_argument("--trials", type=int, default=1)
    q.add_argument("--budget", type=float, default=1.0)
    q.add_argument("--split", default="dev")
    q.add_argument("--types", default="")
    r = sub.add_parser("report")
    r.add_argument("run_dir")
    r.add_argument("--a")
    r.add_argument("--b")
    a = p.parse_args(argv)

    if a.cmd == "report":
        from agentlab.evals.report import compare
        from agentlab.evals.runner import load_trials
        from agentlab.retrieval.qa_eval import render_qa
        trials = load_trials(Path(a.run_dir) / "trials.jsonl")
        print(render_qa(trials))
        if a.a and a.b:
            c = compare(trials, a.a, a.b)
            print(f"{a.b} - {a.a}: {c['diff'] * 100:+.1f} pts [{c['lo'] * 100:+.1f}, {c['hi'] * 100:+.1f}] over "
                  f"{c['tasks']} questions")
        return 0

    split = None if getattr(a, "split", "dev") == "all" else getattr(a, "split", None)
    if a.cmd == "qa":
        from agentlab.retrieval.qa import validate_spec
        specs = [x for x in a.modes.split(",") if x]
        for spec in specs:
            validate_spec(spec)                  # fail fast, before building anything or spending
        needs_dense = any("dense" in x or "hybrid" in x or x in ("agentic", "rag", "rag+archived") for x in specs)
        if needs_dense and a.embedder == "none":
            raise SystemExit("dense/hybrid modes need an embedder (--embedder hash|fastembed)")
    if a.cmd in ("qa", "eval-retrieval", "search") and a.embedder.startswith("hash"):
        print("NOTE: --embedder hash is a spelling-overlap stand-in for tests, not a semantic model. 'dense' and "
              "'hybrid' numbers below are NOT dense retrieval. Use --embedder fastembed for real results.\n")
    idx, secs = open_index(a.embedder, a.max_chars, a.overlap)
    if a.cmd == "index":
        print(json.dumps(idx.stats(), indent=2), f"\n(ready in {secs:.1f}s)")
    elif a.cmd == "search":
        for h in idx.search(a.query, a.k, a.mode, a.archived):
            print(f"{h.score:8.4f}  {h.chunk_id:28} [{h.status}] {h.heading}\n          "
                  f"{h.text.splitlines()[1] if len(h.text.splitlines()) > 1 else ''}"[:200])
    elif a.cmd == "eval-retrieval":
        from agentlab.retrieval.qa_eval import load_qa, render_retrieval, retrieval_eval
        tasks = load_qa(a.suite, split=split)
        modes = [m for m in a.modes.split(",") if m and (m == "bm25" or idx.embedder)]
        res = retrieval_eval(tasks, idx, modes, a.k, a.archived)
        print(f"# Retrieval eval: {len(tasks)} questions, embedder={idx.stats()['embedder']}\n")
        print(render_retrieval(res))
    elif a.cmd == "qa":
        from agentlab.costs import Budget
        from agentlab.llm.registry import get_model
        from agentlab.retrieval.qa_eval import load_qa, render_qa, run_qa
        tasks = load_qa(a.suite, split=split, types=[t for t in a.types.split(",") if t] or None)
        out = new_run_dir(RUNS / "retrieval")
        out.mkdir(parents=True, exist_ok=True)
        (out / "meta.json").write_text(json.dumps({"model": a.model, "modes": specs, "embedder": a.embedder,
                                                   "max_chars": a.max_chars, "overlap": a.overlap,
                                                   "split": a.split, "trials": a.trials}, indent=2))
        from agentlab.costs import BudgetExceeded
        from agentlab.evals.runner import load_trials
        try:
            trials = run_qa(tasks, lambda: get_model(a.model), idx, specs, trials=a.trials,
                            budget=Budget(limit_usd=a.budget, label="retrieval-qa"), out_dir=out)
        except BudgetExceeded as e:
            # report what finished; a partial run is still evidence (and you paid for it)
            print(f"! budget reached ({e}); reporting the completed trials")
            p = out / "trials.jsonl"
            trials = load_trials(p) if p.exists() else []
        md = render_qa(trials) if trials else "no completed trials\n"
        (out / "report.md").write_text(md)
        print(md + f"\nresults: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
