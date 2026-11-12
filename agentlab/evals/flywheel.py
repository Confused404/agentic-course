"""Production traces -> candidate eval tasks for a human to label (TEXTBOOK §10)."""
from __future__ import annotations

import json
from pathlib import Path

import yaml


def _load_spans(trace_dir: Path) -> list[dict]:
    spans = []
    for f in sorted(Path(trace_dir).glob("*.jsonl")):
        spans += [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
    return spans


def mine_traces(trace_dir: Path, min_turns: int = 6) -> list[dict]:
    spans = _load_spans(trace_dir)
    children: dict[str, list[dict]] = {}
    for s in spans:
        if s["parent_id"]:
            children.setdefault(s["parent_id"], []).append(s)

    def descendants(sid: str) -> list[dict]:
        out, stack = [], list(children.get(sid, []))
        while stack:
            c = stack.pop()
            out.append(c)
            stack += children.get(c["span_id"], [])
        return out

    roots = sorted((s for s in spans if s["name"] == "invoke_agent support-chat"), key=lambda s: s["start"])
    # all user messages per session, in turn order, so a flagged turn 2 ("Yes, please do.") keeps its context
    sessions: dict[str, list[tuple[int, str]]] = {}
    for r in roots:
        a = r["attributes"]
        sessions.setdefault(a.get("course.session_id", r["trace_id"]), []).append(
            (int(a.get("course.turn_index", 1)), a.get("course.user_message", "")))
    cands = []
    for root in roots:
        desc = descendants(root["span_id"])
        tools = [d for d in sorted(desc, key=lambda d: d["start"]) if d["name"].startswith("execute_tool ")]
        reasons = []
        if any(d["attributes"].get("course.tool.is_error") for d in tools):
            reasons.append("tool_error")
        if any(d["name"] == "execute_tool escalate_to_human" for d in tools):
            reasons.append("escalated")
        if sum(d["name"].startswith("chat ") for d in desc) >= min_turns:
            reasons.append("long")
        stop = root["attributes"].get("course.stop", "end_turn")
        if stop == "error":
            reasons.append("error")
        elif stop != "end_turn":
            reasons.append("stopped")
        if reasons:
            a = root["attributes"]
            sid, idx = a.get("course.session_id", root["trace_id"]), int(a.get("course.turn_index", 1))
            turns = [m for i, m in sorted(sessions.get(sid, [])) if i <= idx]
            cands.append({"trace_id": root["trace_id"], "customer_id": int(a.get("course.customer_id", 0)),
                          "user_message": a.get("course.user_message", ""), "turns": turns or [a.get("course.user_message", "")],
                          "reasons": reasons, "tools": [d["name"].removeprefix("execute_tool ") for d in tools]})
    return cands


def candidates_to_yaml(cands: list[dict]) -> str:
    stubs = [{"id": f"cand_{c['trace_id'][:8]}", "customer_id": c["customer_id"], "turns": c.get("turns") or [c["user_message"]],
              "graders": [], "tags": ["from-production"],
              "note": f"from trace {c['trace_id']}; reasons: {', '.join(c['reasons'])}; tools: {c['tools']}. "
                      f"TODO: write the expected outcome as graders."} for c in cands]
    return yaml.safe_dump(stubs, sort_keys=False, allow_unicode=True)
