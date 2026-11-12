"""Pinning MCP tool definitions, like a lockfile pins dependencies. AGENT-OFF (reference solution): written by hand in Node 11 YOU_DO
task 2.

ToolDef is GIVEN (the client and the tests import it). Implement fingerprint(), diff_pins() and find_collisions()
to satisfy their docstrings. Tests: nodes/11-mcp/tests/test_pins.py. Read TEXTBOOK §5 (tool poisoning, rug pulls,
shadowing) first. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolDef:
    server: str                      # the name YOU gave the server in your config (not what it calls itself)
    name: str                        # the tool's name as the server lists it
    description: str
    input_schema: dict
    annotations: dict = field(default_factory=dict)   # hints like {"read_only_hint": True}: claims, not guarantees

    @property
    def key(self) -> str:
        """The lockfile key: '<server>/<name>'."""
        return f"{self.server}/{self.name}"


@dataclass
class PinReport:
    added: list[str] = field(default_factory=list)      # keys listed now, not in the lockfile
    changed: list[str] = field(default_factory=list)    # keys in both, different fingerprint
    removed: list[str] = field(default_factory=list)    # keys in the lockfile, not listed now
    unchanged: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.added or self.changed)


def fingerprint(tool: ToolDef) -> str:
    """A stable hex SHA-256 of everything the MODEL reads about a tool. Contract (each line is tested):

    1. Covers name, description, input_schema and annotations. Any change to any of them changes the fingerprint
       (including whitespace or invisible characters in the description: those are where poison hides).
    2. Does NOT cover `server` (renaming a server in your config isn't a change to the tool).
    3. Independent of dict key order at every nesting level (servers may serialise schemas in any order), but
       sensitive to list order (["a", "b"] != ["b", "a"]: e.g. an enum's order is shown to the model).
    4. Deterministic across processes and Python versions: no hash(), no repr() of dicts.
    5. Returns 64 lowercase hex characters.
    """
    # why sort_keys + separators: canonical JSON is order-independent for dicts, order-preserving for lists, and the
    # same bytes on every machine; ensure_ascii keeps invisible Unicode visible as escapes (and in the hash)
    doc = {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema,
           "annotations": tool.annotations}
    canon = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def diff_pins(pinned: dict[str, str], current: list[ToolDef]) -> PinReport:
    """Compare a lockfile (key -> fingerprint) with what servers list now.

    Every list in the report is sorted. A key listed twice in `current` (a buggy or malicious server) is reported
    once: if it's in the lockfile, it's changed when its fingerprints differ from each other or from the pin;
    if it isn't, it's added.
    Keys in `pinned` whose server has NO tools in `current` at all are not "removed" (that server may simply not be
    connected right now); keys of a connected server that are no longer listed are removed.
    """
    report = PinReport()
    seen: dict[str, set[str]] = {}
    for t in current:
        seen.setdefault(t.key, set()).add(fingerprint(t))
    for key, fps in seen.items():
        if key not in pinned:
            report.added.append(key)
        elif len(fps) > 1 or pinned[key] not in fps:
            report.changed.append(key)
        else:
            report.unchanged.append(key)
    connected = {t.server for t in current}
    # why only connected servers: a server that's down today hasn't removed its tools; you just can't see them
    report.removed = [k for k in pinned if k not in seen and k.split("/", 1)[0] in connected]
    for lst in (report.added, report.changed, report.removed, report.unchanged):
        lst.sort()
    return report


def find_collisions(tools: list[ToolDef]) -> dict[str, list[str]]:
    """Tool names offered by more than one server: {name: sorted list of servers}. Names compare case-insensitively
    and ignoring '-' vs '_' (a model reading "get-order" and "get_order" sees the same tool); the dict key is the
    normalised name (lowercase, '-' -> '_'). Names offered by only one server are not in the result, even if that
    server lists them twice."""
    by_name: dict[str, set[str]] = {}
    for t in tools:
        by_name.setdefault(t.name.lower().replace("-", "_"), set()).add(t.server)
    return {n: sorted(s) for n, s in sorted(by_name.items()) if len(s) > 1}
