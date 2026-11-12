import json
import sys

import anyio
from mcp import Client, StdioServerParameters

from agentlab.llm.types import ToolUseBlock
from agentlab.mcpkit.bridge import Doc, annotations_for, registry_server
from agentlab.mcpkit.shop_server import build_shop_server
from agentlab.tools.base import Tool, ToolRegistry
from agentlab.tools.errors import ToolError


def _reg():
    def add(a: int, b: int):
        return {"sum": a + b}

    def boom(x: str):
        raise ToolError("x must be a known code; try 'A'")
    obj = {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
           "required": ["a", "b"], "additionalProperties": False}
    return ToolRegistry([Tool("add", "Add two integers.", obj, add),
                         Tool("boom", "Fails helpfully.", {"type": "object", "properties": {"x": {"type": "string"}},
                                                           "required": ["x"]}, boom, side_effects=True)])


async def _session(server, fn):
    async with Client(server) as c:
        return await fn(c)


def test_registry_over_mcp_is_the_same_tools():
    reg = _reg()
    srv = registry_server("calc", reg, docs=[Doc("help://x", "x", "X doc", "# X")])

    async def go(c):
        tools = (await c.list_tools()).tools
        ok = await c.call_tool("add", {"a": 2, "b": 3})
        bad = await c.call_tool("add", {"a": "two", "b": 3})
        err = await c.call_tool("boom", {"x": "?"})
        res = (await c.list_resources()).resources
        text = (await c.read_resource("help://x")).contents[0].text
        return tools, ok, bad, err, res, text
    tools, ok, bad, err, res, text = anyio.run(_session, srv, go)
    assert [t.name for t in tools] == reg.names()
    assert {t.name: dict(t.input_schema) for t in tools} == {s.name: s.input_schema for s in reg.specs()}
    assert tools[0].annotations.read_only_hint is True and tools[1].annotations.destructive_hint is True
    assert not ok.is_error and json.loads(ok.content[0].text) == {"sum": 5}
    assert bad.is_error and "expected integer" in bad.content[0].text, "the registry's validation message, verbatim"
    assert err.is_error and "try 'A'" in err.content[0].text, "ToolError text reaches the model unchanged"
    assert [str(r.uri) for r in res] == ["help://x"] and text == "# X"


def test_annotations_follow_side_effects():
    reg = _reg()
    assert annotations_for(reg.get("add")).read_only_hint is True
    assert annotations_for(reg.get("boom")).destructive_hint is True


def test_shop_server_scopes_to_its_customer(conn):
    srv = build_shop_server(conn, 9001)

    async def go(c):
        mine = await c.call_tool("lookup_order", {"order_id": 4822})
        theirs = await c.call_tool("lookup_order", {"order_id": 4826})
        docs = (await c.list_resources()).resources
        return mine, theirs, docs
    mine, theirs, docs = anyio.run(_session, srv, go)
    assert not mine.is_error and "4822" in mine.content[0].text
    assert theirs.is_error, "another customer's order is not found"
    assert any(str(d.uri).startswith("help://") for d in docs)


def test_shop_server_over_stdio(db_path):
    """The real transport: a subprocess speaking JSON-RPC on stdout. Anything else printed to stdout breaks it."""
    params = StdioServerParameters(command=sys.executable, args=["-m", "agentlab.mcpkit.shop_server", "--customer",
                                                                 "9001", "--db", str(db_path)])

    async def go(c):
        names = [t.name for t in (await c.list_tools()).tools]
        r = await c.call_tool("lookup_order", {"order_id": 4821})
        return names, r
    names, r = anyio.run(_session, params, go)
    assert "issue_refund" in names and not r.is_error


def test_registry_execute_unchanged_by_bridge():
    reg = _reg()
    direct = reg.execute(ToolUseBlock("1", "add", {"a": 1, "b": 1}))
    assert json.loads(direct.text) == {"sum": 2}
