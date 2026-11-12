"""Least privilege from a token: a session sees and can call only the tools its scopes allow (TEXTBOOK §3-§4)."""
from __future__ import annotations

import sqlite3

from agentlab.authz import tokens as tokens_module
from agentlab.authz.scopes import TOOL_SCOPES
from agentlab.authz.tokens import Principal, TokenError
from agentlab.llm.types import ToolResultBlock, ToolUseBlock
from agentlab.tools.base import ToolRegistry

AUDIENCE = "shopfront-mcp"


def allowed(tool_name: str, principal: Principal) -> bool:
    need = TOOL_SCOPES.get(tool_name)
    # why unknown tools are excluded: a tool nobody classified has no scope, and "no scope" must not mean "open"
    return need is not None and (need == "public" or need in principal.scopes)


def scoped_registry(registry: ToolRegistry, principal: Principal) -> ToolRegistry:
    """Only the tools this principal may use. why at LISTING time: a tool the model never sees is a tool it can't be
    talked into calling (and it saves tokens: Node 11 §4)."""
    return ToolRegistry([registry.get(n) for n in registry.names() if allowed(n, principal)])


class ScopedExecutor:
    """Defense in depth: check again at CALL time, in case the listing and the caller disagree, and stop working
    when the token expires (a session must not outlive its credential)."""

    def __init__(self, registry: ToolRegistry, principal: Principal, clock=None) -> None:
        import time
        self.registry, self.principal = scoped_registry(registry, principal), principal
        self.clock = clock or (lambda: int(time.time()))

    def specs(self):
        return self.registry.specs()

    def execute(self, call: ToolUseBlock) -> ToolResultBlock:
        if self.clock() >= self.principal.expires_at:
            return ToolResultBlock(call.id, "This session's authorization has expired; the user must sign in again.",
                                   is_error=True)
        if not allowed(call.name, self.principal):
            need = TOOL_SCOPES.get(call.name, "an unknown scope")
            return ToolResultBlock(call.id, f"'{call.name}' is not permitted for this session (needs {need}).",
                                   is_error=True)
        return self.registry.execute(call)


def shop_tools_for_token(conn: sqlite3.Connection, token: str, secret: bytes, *, now: int,
                         audience: str = AUDIENCE, variant: str = "v2") -> tuple[ScopedExecutor, Principal]:
    """Verify the token, then build the support tools FOR ITS CUSTOMER with ITS scopes. The customer comes from the
    verified token, never from the model or the request body (the confused-deputy fix, TEXTBOOK §4)."""
    from agentlab.assistant.tools import make_support_tools
    p = tokens_module.verify_token(token, secret, audience=audience, now=now)
    if p.customer_id is None:
        raise TokenError("insufficient_scope", "token is not bound to a customer")
    return ScopedExecutor(make_support_tools(conn, p.customer_id, actor=f"agent:{p.sub}", variant=variant), p), p


def authorized_shop_server(conn: sqlite3.Connection, token: str, secret: bytes, *, now: int,
                           audience: str = AUDIENCE):
    """The Node 11 bridge over the scoped tools: an MCP server whose tools/list depends on who's asking."""
    from agentlab.mcpkit.bridge import registry_server
    ex, p = shop_tools_for_token(conn, token, secret, now=now, audience=audience)
    return registry_server("shopfront", ex.registry, instructions=f"Shopfront tools for {p.sub}.")
