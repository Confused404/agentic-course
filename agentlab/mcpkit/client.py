"""MCPToolset: tools from several MCP servers, presented to the agent loop as one ToolExecutor (TEXTBOOK §3-§6).

The loop is synchronous; the MCP SDK is async. One background event-loop thread (an anyio blocking portal) owns every
client connection, and each sync call is handed to it.

What the toolset adds on top of "list tools, call tools":
  - namespacing: the model sees "<server>__<tool>", so two servers can't offer the same name (shadowing, §5)
  - an allowlist per server (least privilege: load only what this task needs)
  - pinning (§5): definitions are fingerprinted; under policy "enforce", tools that are new or changed since the
    lockfile was approved are hidden from the model and refused if called
  - client-side argument validation, so a bad call gets a message the model can act on (Node 05)
  - errors as data: protocol errors and tool errors both become error results, never exceptions in the loop
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from anyio.from_thread import start_blocking_portal
from mcp import Client

from agentlab.llm.types import ToolResultBlock, ToolSpec, ToolUseBlock
from agentlab.mcpkit import pins as pins_module
from agentlab.mcpkit.pins import PinReport, ToolDef
from agentlab.tools.base import validate_args

log = logging.getLogger(__name__)
SEP = "__"
Policy = Literal["off", "warn", "enforce"]


def to_tooldef(server: str, t: Any) -> ToolDef:
    ann = t.annotations.model_dump(exclude_none=True) if t.annotations else {}
    return ToolDef(server, t.name, t.description or "", dict(t.input_schema or {}), ann)


def _result_text(r: Any) -> str:
    texts = [c.text for c in r.content if getattr(c, "type", None) == "text"]
    if texts:
        return "\n".join(texts)
    if r.structured_content is not None:
        return json.dumps(r.structured_content, sort_keys=True)
    kinds = sorted({getattr(c, "type", "?") for c in r.content})
    return f"(non-text result: {', '.join(kinds) or 'empty'})"


@dataclass
class Exposed:
    exposed_name: str            # what the model sees and calls
    tool: ToolDef


@dataclass
class MCPToolset:
    servers: dict[str, Any]                       # config name -> Client target (Server, MCPServer, stdio params, URL)
    namespace: bool = True
    allow: dict[str, set[str]] | None = None      # server -> tool names to expose (None = all)
    lockfile: Path | None = None
    policy: Policy = "off"
    timeout_s: float = 30.0                       # per request: a hung server must not hang the agent loop
    events: list[str] = field(default_factory=list)          # warnings and refusals, for the eval and the user
    _defs: list[ToolDef] = field(default_factory=list, init=False)
    _exposed: dict[str, Exposed] = field(default_factory=dict, init=False)
    _blocked: set[str] = field(default_factory=set, init=False)        # keys hidden by the pin policy
    _clients: dict[str, Any] = field(default_factory=dict, init=False)
    _cms: list = field(default_factory=list, init=False)
    _portal_cm: Any = field(default=None, init=False)
    _portal: Any = field(default=None, init=False)
    last_report: PinReport | None = field(default=None, init=False)

    # ---------------------------------------------------------------- lifecycle
    def __enter__(self) -> "MCPToolset":
        bad = [n for n in self.servers if SEP in n]
        if bad:
            # why: "a" + tool "b__c" and "a__b" + tool "c" would both be exposed as "a__b__c"
            raise ValueError(f"server names may not contain {SEP!r}: {bad}")
        self._portal_cm = start_blocking_portal()
        self._portal = self._portal_cm.__enter__()
        try:
            for name, target in self.servers.items():
                cm = self._portal.wrap_async_context_manager(Client(target, read_timeout_seconds=self.timeout_s))
                self._clients[name] = cm.__enter__()
                self._cms.append(cm)
            self.refresh()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        for cm in reversed(self._cms):
            try:
                cm.__exit__(None, None, None)
            except Exception as e:  # noqa: BLE001 - closing one server must not leak the others
                log.warning("error closing MCP client: %s", e)
        self._cms.clear()
        self._clients.clear()
        self._exposed = {}
        if self._portal_cm is not None:
            self._portal_cm.__exit__(None, None, None)
            self._portal_cm = self._portal = None

    # ---------------------------------------------------------------- discovery
    def refresh(self) -> PinReport | None:
        """Re-list every server's tools and rebuild what the model sees. Call between sessions (or turns) to catch
        definitions that changed after approval (a rug pull)."""
        defs: list[ToolDef] = []
        for name, c in self._clients.items():
            cursor = None
            while True:
                # why cache_mode="refresh": 2026-07-28 servers send ttlMs cache hints and the client honours them;
                # a cached listing would hide exactly the change (rug pull) a refresh exists to catch
                page = self._portal.call(lambda: c.list_tools(cursor=cursor, cache_mode="refresh"))
                defs += [to_tooldef(name, t) for t in page.tools]
                cursor = page.next_cursor
                if not cursor:
                    break
        self._defs = defs
        return self._apply_policy()

    def _apply_policy(self) -> PinReport | None:
        """Compare the current definitions with the lockfile and rebuild what the model sees (no re-listing)."""
        defs = self._defs
        self._blocked = set()
        report = None
        if self.policy != "off":
            pinned = self.load_pins()
            report = pins_module.diff_pins(pinned, defs)
            self.last_report = report
            for key in report.added + report.changed:
                kind = "new" if key in report.added else "CHANGED since approval"
                ev = f"pin: {key} is {kind}" + (" (hidden)" if self.policy == "enforce" else "")
                if ev not in self.events:          # why: re-listing shouldn't repeat the same warning forever
                    self.events.append(ev)
            if self.policy == "enforce":
                self._blocked = set(report.added) | set(report.changed)
        self._build_exposed()
        return report

    def _build_exposed(self) -> None:
        self._exposed = {}
        for t in self._defs:
            if self.allow is not None and t.name not in self.allow.get(t.server, set()):
                continue
            if t.key in self._blocked:
                continue
            exposed = f"{t.server}{SEP}{t.name}" if self.namespace else t.name
            if exposed in self._exposed:
                # why record it: without namespacing, a second server silently replaces the first one's tool.
                # That's the shadowing attack (§5), and naive clients behave exactly like this.
                prev = self._exposed[exposed].tool.server
                self.events.append(f"collision: {t.name!r} from {t.server} replaces the one from {prev}")
            self._exposed[exposed] = Exposed(exposed, t)

    def server_of(self, exposed_name: str) -> str | None:
        """Which server a model-facing tool name is routed to (after namespacing and collisions)."""
        e = self._exposed.get(exposed_name)
        return e.tool.server if e else None

    def tool_defs(self) -> list[ToolDef]:
        return list(self._defs)

    def collisions(self) -> dict[str, list[str]]:
        return pins_module.find_collisions(self._defs)

    # ---------------------------------------------------------------- pins
    def load_pins(self) -> dict[str, str]:
        if self.lockfile and Path(self.lockfile).exists():
            return json.loads(Path(self.lockfile).read_text())
        return {}

    def approve(self, keys: list[str] | None = None) -> dict[str, str]:
        """Pin the CURRENT definitions (all, or only `keys`) into the lockfile, then re-apply the policy.
        why explicit: approving is a human decision made after reading the descriptions (YOU_DO task 5)."""
        if not self.lockfile:
            raise ValueError("no lockfile configured")
        pinned = self.load_pins()
        connected = {t.server for t in self._defs}
        listed = {t.key for t in self._defs}
        pinned = {k: v for k, v in pinned.items() if k.split("/", 1)[0] not in connected or k in listed}
        for t in self._defs:
            if keys is None or t.key in keys:
                pinned[t.key] = pins_module.fingerprint(t)
        Path(self.lockfile).parent.mkdir(parents=True, exist_ok=True)
        Path(self.lockfile).write_text(json.dumps(dict(sorted(pinned.items())), indent=2) + "\n")
        self._apply_policy()        # why not refresh(): approve what you READ, not a fresh listing you haven't seen
        return pinned

    # ---------------------------------------------------------------- ToolExecutor
    def specs(self) -> list[ToolSpec]:
        # why sorted: a stable tool order keeps prompt caches valid (Node 01 §3; the 2026-07-28 spec asks servers
        # for a deterministic order for the same reason)
        return [ToolSpec(n, e.tool.description, e.tool.input_schema) for n, e in sorted(self._exposed.items())]

    def execute(self, call: ToolUseBlock) -> ToolResultBlock:
        e = self._exposed.get(call.name)
        if e is None:
            blocked = [t.key for t in self._defs if t.key in self._blocked
                       and call.name in (t.name, f"{t.server}{SEP}{t.name}")]
            if blocked:
                self.events.append(f"refused: {call.name} (not approved)")
                return ToolResultBlock(call.id, f"Tool '{call.name}' is not approved for use (its definition is new "
                                                f"or changed since it was reviewed).", is_error=True)
            return ToolResultBlock(call.id, f"Unknown tool '{call.name}'. Available tools: "
                                            f"{', '.join(sorted(self._exposed))}.", is_error=True)
        problems = validate_args(e.tool.input_schema, call.input)
        if problems:
            return ToolResultBlock(call.id, f"Invalid arguments for {call.name}: " + "; ".join(problems),
                                   is_error=True)
        client = self._clients.get(e.tool.server)
        if client is None:
            return ToolResultBlock(call.id, f"Tool {call.name} is unavailable: its server is disconnected.",
                                   is_error=True)
        try:
            r = self._portal.call(lambda: client.call_tool(e.tool.name, dict(call.input)))
        except Exception as ex:  # noqa: BLE001 - protocol errors are data for the model too
            return ToolResultBlock(call.id, f"Tool {call.name} failed: {type(ex).__name__}: {ex}", is_error=True)
        return ToolResultBlock(call.id, _result_text(r), is_error=bool(r.is_error))

    # ---------------------------------------------------------------- resources
    def list_resources(self, server: str) -> list[dict]:
        c = self._clients[server]
        return [{"uri": str(r.uri), "name": r.name, "description": r.description}
                for r in self._portal.call(c.list_resources).resources]

    def read_resource(self, server: str, uri: str) -> str:
        c = self._clients[server]
        r = self._portal.call(lambda: c.read_resource(uri))
        return "\n".join(getattr(x, "text", "") for x in r.contents)

    # ---------------------------------------------------------------- cost
    def definition_tokens(self) -> dict[str, int]:
        """Estimated tokens each server's EXPOSED tool definitions add to every request (TEXTBOOK §4)."""
        from agentlab.context.tokens import estimate_tokens
        out: dict[str, int] = {}
        for n, e in self._exposed.items():
            text = json.dumps({"name": n, "description": e.tool.description, "input_schema": e.tool.input_schema})
            out[e.tool.server] = out.get(e.tool.server, 0) + estimate_tokens(text)
        return out
