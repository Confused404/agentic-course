"""Calibrate the LLM judge against YOUR labels (Node 04 YOU_DO step 5). Given; not part of the ticket.

    .venv/bin/python nodes/04-evals/judge_calibration.py runs/evals/<run_dir> [--max 25]

Shows you each judged trial's rubric and transcript WITHOUT the judge's verdict, asks for your label
(p = pass, f = fail, u = unknown, s = skip), then prints raw agreement, Cohen's kappa, the judge's recall on YOUR failures, and the disagreements to read.
Labels are saved to <run_dir>/human_labels.jsonl so you can stop and resume.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agentlab.evals.runner import load_trials  # noqa: E402
from agentlab.evals.task import load_tasks  # noqa: E402

SUITE = Path(__file__).resolve().parent / "evals" / "support"


def render(transcript: list[dict]) -> str:
    out = []
    for m in transcript:
        for b in m["content"]:
            if b["type"] == "text" and b["text"].strip():
                out.append(f"{'CUSTOMER' if m['role'] == 'user' else 'ASSISTANT'}: {b['text'].strip()}")
            elif b["type"] == "tool_use":
                out.append(f"  TOOL CALL {b['name']}({json.dumps(b['input'])})")
            elif b["type"] == "tool_result":
                text = b["content"] if isinstance(b["content"], str) else str(b["content"])
                out.append(f"  TOOL RESULT: {text[:300]}")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--max", type=int, default=25)
    a = ap.parse_args()
    run = Path(a.run_dir)
    rubrics = {t.id: [g["rubric"] for g in t.graders if g["type"] == "judge"] for t in load_tasks(SUITE)}
    labels_path = run / "human_labels.jsonl"
    done = {}
    if labels_path.exists():
        for line in labels_path.read_text().splitlines():
            d = json.loads(line)
            done[(d["task_id"], d["model"], d["trial"])] = d
    items = [t for t in load_trials(run / "trials.jsonl") if any(g.grader.startswith("judge") for g in t.grades)]
    new = 0
    for t in items:
        key = (t.task_id, t.model, t.trial)
        if key in done:
            continue
        if new >= a.max:
            break
        new += 1
        rubs = rubrics.get(t.task_id, ["?"])
        print("\n" + "=" * 100 + f"\n{t.task_id}  ({t.model}, trial {t.trial})")
        for i, r in enumerate(rubs, 1):
            print(f"RUBRIC {i}: {r}")
        print("(label the FIRST rubric; others are shown for context)\n")
        print(render(t.transcript))
        ans = ""
        while ans not in ("p", "f", "u", "s", "q"):
            ans = input("\nyour verdict [p/f/u, s=skip, q=quit]: ").strip().lower()
        if ans == "q":
            break
        if ans == "s":
            continue
        judge = next(g for g in t.grades if g.grader.startswith("judge"))
        rec = {"task_id": t.task_id, "model": t.model, "trial": t.trial,
               "human": {"p": "pass", "f": "fail", "u": "unknown"}[ans], "judge": judge.verdict, "judge_reason": judge.detail}
        done[key] = rec
        with open(labels_path, "a") as f:
            f.write(json.dumps(rec) + "\n")
    recs = list(done.values())
    if not recs:
        print("no labels yet")
        return
    agree = sum(r["human"] == r["judge"] for r in recs)
    n = len(recs)
    p_o = agree / n
    cats = ("pass", "fail", "unknown")
    p_e = sum((sum(r["human"] == c for r in recs) / n) * (sum(r["judge"] == c for r in recs) / n) for c in cats)
    kappa = (p_o - p_e) / (1 - p_e) if p_e < 1 else float("nan")
    human_fails = [r for r in recs if r["human"] == "fail"]
    recall = (sum(r["judge"] == "fail" for r in human_fails) / len(human_fails)) if human_fails else None
    print(f"\nRaw agreement: {agree}/{n} = {p_o:.0%}   (compute its Wilson interval with your stats.py)")
    print(f"Cohen's kappa: {kappa:.2f}   (chance-corrected; >= 0.6 usable, >= 0.8 good)")
    print(f"Judge recall on your failures: " + (f"{recall:.0%} of {len(human_fails)}" if recall is not None
                                                 else "n/a: you labelled no failures, so you can't tell if it catches any"))
    cm: dict[tuple, int] = {}
    for r in recs:
        cm[(r["human"], r["judge"])] = cm.get((r["human"], r["judge"]), 0) + 1
    print("confusion (human -> judge):", {f"{h}->{j}": n for (h, j), n in sorted(cm.items())})
    for r in recs:
        if r["human"] != r["judge"]:
            print(f"- {r['task_id']} {r['model']} t{r['trial']}: you={r['human']} judge={r['judge']}: {r['judge_reason'][:200]}")


if __name__ == "__main__":
    main()
