"""Serve any ToolRegistry over MCP (TEXTBOOK §2: MCP is a wire format for the tools you already have).

The schemas, descriptions and errors the model sees are exactly the registry's: MCP adds discovery and transport,
not tool design. Resources are optional read-only documents the HOST (not the model) can choose to show.
"""
from __future__ import annotations

from dataclasses import dataclass

import mcp_types as types
from mcp.server.lowlevel import Server

from agentlab.llm.types import ToolUseBlock
from agentlab.tools.base import Tool, ToolRegistry


@dataclass(frozen=True)
class Doc:
    uri: str
    name: str
    description: str
    text: str
    mime_type: str = "text/markdown"


def annotations_for(tool: Tool) -> types.ToolAnnotations:
    """Hints for the HOST's approval UI. why honest hints matter: a client may auto-approve read-only tools, so a
    write tool marked read-only is a lie with consequences. And why hosts must not TRUST them: any server can lie."""
    return types.ToolAnnotations(read_only_hint=not tool.side_effects, destructive_hint=tool.side_effects,
                                 idempotent_hint=not tool.side_effects, open_world_hint=False)


def registry_server(name: str, registry: ToolRegistry, *, docs: list[Doc] = (), instructions: str | None = None,
                    version: str = "1.0.0") -> Server:
    by_uri = {d.uri: d for d in docs}

    async def list_tools(ctx, params) -> types.ListToolsResult:
        # why registry.specs(): already sorted by name; a deterministic order keeps clients' prompt caches warm
        return types.ListToolsResult(tools=[
            types.Tool(name=s.name, description=s.description, input_schema=s.input_schema,
                       annotations=annotations_for(registry.get(s.name))) for s in registry.specs()])

    async def call_tool(ctx, params) -> types.CallToolResult:
        # why registry.execute: validation, ToolError messages and "errors are data" are the registry's (Node 05)
        res = registry.execute(ToolUseBlock("mcp", params.name, dict(params.arguments or {})))
        return types.CallToolResult(content=[types.TextContent(type="text", text=res.text)], is_error=res.is_error)

    async def list_resources(ctx, params) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=[
            types.Resource(uri=d.uri, name=d.name, description=d.description, mime_type=d.mime_type) for d in docs])

    async def read_resource(ctx, params) -> types.ReadResourceResult:
        d = by_uri.get(str(params.uri))
        if d is None:
            from mcp.shared.exceptions import MCPError
            raise MCPError(code=-32602, message=f"Unknown resource {params.uri}")   # 2026-07-28: not found = -32602
        return types.ReadResourceResult(contents=[types.TextResourceContents(uri=d.uri, mime_type=d.mime_type,
                                                                             text=d.text)])

    return Server(name, version=version, instructions=instructions, on_list_tools=list_tools,
                  on_call_tool=call_tool, on_list_resources=list_resources if docs else None,
                  on_read_resource=read_resource if docs else None)
