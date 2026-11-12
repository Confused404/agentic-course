"""Static checks for tool definitions and system prompts (TEXTBOOK §2-§3). Catches the mechanical smells so reviews
and experiments can focus on behaviour."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from agentlab.llm.types import ToolSpec

CATEGORICAL = {"reason", "status", "type", "kind", "category", "priority"}
MONEY_TIME = ("amount", "price", "cost", "total", "timeout", "duration", "delay")
UNITS = ("_cents", "_usd", "_dollars", "_s", "_ms", "_seconds", "_minutes", "_days")
ACRONYMS = {"JSON", "HTTP", "HTTPS", "HTML", "USPS", "UTC", "API", "URL", "SKU", "FAQ", "USD", "CAD", "ISO"}


@dataclass
class Finding:
    level: str
    where: str
    rule: str
    message: str


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def lint_tools(specs: list[ToolSpec]) -> list[Finding]:
    out: list[Finding] = []
    E = lambda w, r, m: out.append(Finding("error", w, r, m))    # noqa: E731
    W = lambda w, r, m: out.append(Finding("warning", w, r, m))  # noqa: E731
    names = [s.name for s in specs]
    for n in sorted({n for n in names if names.count(n) > 1}):
        E(n, "duplicate-name", f"{names.count(n)} tools are called {n!r}")
    for s in specs:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", s.name):
            E(s.name, "name-format", "use snake_case, 2-64 chars, starting with a letter")
        d = s.description or ""
        if len(d) < 40:
            E(s.name, "desc-too-short", f"description has {len(d)} chars; say what it does, when to use it, what it returns")
        if not re.search(r"\b(use|when|only after|before)\b", d, re.I):
            W(s.name, "desc-no-when", "description doesn't say when to use it")
        if not re.search(r"\breturn", d, re.I):
            W(s.name, "desc-no-returns", "description doesn't say what it returns")
        sch = s.input_schema or {}
        if sch.get("type") != "object":
            E(s.name, "schema-not-object", "input_schema must be {'type': 'object', ...}")
            continue
        props = sch.get("properties", {})
        for r in sch.get("required", []):
            if r not in props:
                E(s.name, "required-unknown", f"required field {r!r} is not in properties")
        if sch.get("additionalProperties") is not False:
            W(s.name, "additional-properties", "set additionalProperties: false so typos become errors")
        for p, ps in props.items():
            if "type" not in ps:
                E(s.name, "param-no-type", f"parameter {p!r} has no type")
            if "description" not in ps:
                W(s.name, "param-no-description", f"parameter {p!r} has no description (add meaning + an example)")
            if ps.get("type") == "string" and (p in CATEGORICAL or p.endswith(("_type", "_status"))) and "enum" not in ps:
                W(s.name, "categorical-no-enum", f"parameter {p!r} looks categorical; use an enum")
            if ps.get("type") in ("integer", "number") and any(k in p for k in MONEY_TIME) and not p.endswith(UNITS):
                W(s.name, "number-no-unit", f"parameter {p!r} needs a unit suffix ({', '.join(UNITS)})")
    uniq = sorted(set(names))
    for i, a in enumerate(uniq):
        for b in uniq[i + 1:]:
            if a.startswith(b) or b.startswith(a) or _edit_distance(a, b) <= 2:
                W(f"{a}/{b}", "confusable-names", f"{a!r} and {b!r} are easy to confuse")
    est = len(json.dumps([s.__dict__ for s in specs])) / 4
    if est > 4000:
        W("tools", "tools-too-long", f"tool definitions are ~{est:.0f} tokens, sent on every call")
    return out


def lint_prompt(text: str, required_placeholders: tuple[str, ...] = ("{today}",)) -> list[Finding]:
    out: list[Finding] = []
    for ph in required_placeholders:
        if ph not in text:
            out.append(Finding("error", "prompt", "missing-placeholder", f"{ph} is missing"))
        elif text.index(ph) < 0.2 * len(text):
            out.append(Finding("warning", "prompt", "volatile-early",
                               f"{ph} appears in the first 20% of the prompt; put per-request/per-day content at "
                               f"the end so the stable prefix stays cacheable"))
    stripped = re.sub(r"\{[^}]*\}", "", text)
    caps = [w for w in re.findall(r"\b[A-Z]{4,}\b", stripped) if w not in ACRONYMS]
    if len(caps) > 3:
        out.append(Finding("warning", "prompt", "shouting", f"{len(caps)} ALL-CAPS words: {sorted(set(caps))[:8]}"))
    absolutes = re.findall(r"\b(never|always|must)\b", text, re.I)
    if len(absolutes) > 6:
        out.append(Finding("warning", "prompt", "absolutes", f"{len(absolutes)} never/always/must"))
    if len(text) / 4 > 2000:
        out.append(Finding("warning", "prompt", "too-long", f"~{len(text) / 4:.0f} tokens on every call"))
    return out
