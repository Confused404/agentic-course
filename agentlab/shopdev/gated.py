"""Every shopdev tool call passes the permission gate first (TEXTBOOK §5)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from agentlab.llm.types import ToolResultBlock, ToolSpec, ToolUseBlock
from agentlab.shopdev.permissions import Decision
from agentlab.tools import ToolRegistry

Approver = Callable[[str, dict, str], bool]


@dataclass
class GateLogEntry:
    tool: str
    args: dict
    action: str
    reason: str
    approved: bool | None = None


class GatedExecutor:
    def __init__(self, registry: ToolRegistry, gate, approver: Approver) -> None:
        self.registry, self.gate, self.approver = registry, gate, approver
        self.log: list[GateLogEntry] = []

    def specs(self) -> list[ToolSpec]:
        return self.registry.specs()

    def execute(self, call: ToolUseBlock) -> ToolResultBlock:
        try:
            d = self.gate.decide(call.name, call.input)
        except Exception:  # noqa: BLE001
            d = Decision("deny", "permission check failed")      # why: a broken gate must fail CLOSED
        entry = GateLogEntry(call.name, dict(call.input), d.action, d.reason)
        self.log.append(entry)
        if d.action == "deny":
            return ToolResultBlock(call.id, f"Denied by policy: {d.reason}", is_error=True)
        if d.action == "ask":
            try:
                entry.approved = bool(self.approver(call.name, call.input, d.reason))
            except Exception:  # noqa: BLE001 - e.g. EOFError with no terminal: no answer means no
                entry.approved = False
            if not entry.approved:
                return ToolResultBlock(call.id, f"Denied by the user: {d.reason}. Try a different approach or "
                                                f"explain why this is needed.", is_error=True)
        return self.registry.execute(call)
