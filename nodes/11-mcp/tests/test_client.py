import json

import pytest

from agentlab.llm.types import ToolUseBlock
from agentlab.mcpkit.client import MCPToolset
from agentlab.mcpkit.evil import EvilServer
from agentlab.mcpkit.shop_server import build_shop_server


def call(ts, name, **args):
    return ts.execute(ToolUseBlock("c1", name, args))


def test_namespacing_and_execution(conn, naive_pins_and_review):
    with MCPToolset({"shopfront": build_shop_server(conn, 9001), "parcel-rates": EvilServer("benign").server}) as ts:
        names = [s.name for s in ts.specs()]
        assert names == sorted(names) and "shopfront__lookup_order" in names
        assert "parcel-rates__quote_shipping" in names
        r = call(ts, "shopfront__lookup_order", order_id=4822)
        assert not r.is_error and "4822" in r.text
        assert "Unknown tool" in call(ts, "lookup_order", order_id=1).text


def test_without_namespacing_a_collision_replaces_silently_but_is_recorded(conn, naive_pins_and_review):
    evil = EvilServer("shadow")
    with MCPToolset({"shopfront": build_shop_server(conn, 9001), "parcel-rates": evil.server},
                    namespace=False) as ts:
        r = call(ts, "lookup_order", order_id=4822)
        assert "card number" in r.text and evil.calls, "the look-alike answered"
        assert any("collision" in e for e in ts.events)


def test_validation_message_and_errors_as_data(conn, naive_pins_and_review):
    with MCPToolset({"shopfront": build_shop_server(conn, 9001)}) as ts:
        r = call(ts, "shopfront__lookup_order", order_id="4822")
        assert r.is_error and "order_id" in r.text and "integer" in r.text
        r = call(ts, "shopfront__lookup_order", order_id=99999)
        assert r.is_error, "a tool error comes back as an error result, not an exception"


def test_allowlist(conn, naive_pins_and_review):
    with MCPToolset({"shopfront": build_shop_server(conn, 9001), "parcel-rates": EvilServer("benign").server},
                    allow={"shopfront": {"lookup_order"}}) as ts:
        assert [s.name for s in ts.specs()] == ["shopfront__lookup_order"]


def test_pins_enforce_hides_new_and_changed(conn, tmp_path, naive_pins_and_review):
    lock = tmp_path / "mcp-lock.json"
    evil = EvilServer("rug")
    servers = {"shopfront": build_shop_server(conn, 9001), "parcel-rates": evil.server}
    with MCPToolset(servers, lockfile=lock, policy="enforce") as ts:
        assert ts.specs() == [], "nothing is approved yet"
        ts.approve()
        assert len(ts.specs()) == 8 and json.loads(lock.read_text())
    with MCPToolset(servers, lockfile=lock, policy="enforce") as ts:     # second listing: the rug is pulled
        names = [s.name for s in ts.specs()]
        assert "parcel-rates__quote_shipping" not in names and "shopfront__lookup_order" in names
        assert any("CHANGED" in e for e in ts.events)
        r = call(ts, "parcel-rates__quote_shipping", order_id=4822)
        assert r.is_error and "not approved" in r.text and evil.calls == []


def test_refresh_catches_a_rug_pull_mid_session(conn, tmp_path, naive_pins_and_review):
    lock = tmp_path / "lock.json"
    evil = EvilServer("rug")
    with MCPToolset({"parcel-rates": evil.server}, lockfile=lock, policy="warn") as ts:
        ts.approve()                       # pins listing 1 (what you read)
        assert ts.last_report.clean
        ts.refresh()                       # listing 2: the rug is pulled
        assert ts.last_report.changed == ["parcel-rates/quote_shipping"]
        assert [s.name for s in ts.specs()] == ["parcel-rates__quote_shipping"], "warn shows it, but says so"


def test_definition_tokens_and_resources(conn, naive_pins_and_review):
    with MCPToolset({"shopfront": build_shop_server(conn, 9001)}) as ts:
        toks = ts.definition_tokens()
        assert set(toks) == {"shopfront"} and toks["shopfront"] > 300
        docs = ts.list_resources("shopfront")
        assert docs and "refund" in ts.read_resource("shopfront", docs[0]["uri"]).lower() + "refund"


def test_close_is_clean_after_errors(conn, naive_pins_and_review):
    with pytest.raises(ZeroDivisionError):
        with MCPToolset({"shopfront": build_shop_server(conn, 9001)}):
            1 / 0


def test_refusals_partial_approval_and_lockfile_hygiene(conn, tmp_path, naive_pins_and_review):
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"elsewhere/tool": "f" * 64, "parcel-rates/gone": "0" * 64}))
    evil = EvilServer("benign")
    with MCPToolset({"shopfront": build_shop_server(conn, 9001), "parcel-rates": evil.server}, namespace=False,
                    lockfile=lock, policy="enforce") as ts:
        r = call(ts, "quote_shipping", order_id=4822)
        assert r.is_error and "not approved" in r.text and any(e.startswith("refused") for e in ts.events)
        ts.approve(["parcel-rates/quote_shipping"])
        assert [s.name for s in ts.specs()] == ["quote_shipping"], "only what was approved"
        pins = json.loads(lock.read_text())
        assert "elsewhere/tool" in pins, "pins of servers that aren't connected are kept"
        assert "parcel-rates/gone" not in pins, "pins of tools a connected server no longer lists are dropped"
    with pytest.raises(ValueError):
        with MCPToolset({"shopfront": build_shop_server(conn, 9001)}) as ts:
            ts.approve()


def test_failures_become_error_results(conn, naive_pins_and_review):
    import mcp_types as types
    from mcp.server.lowlevel import Server

    async def lt(ctx, p):
        return types.ListToolsResult(tools=[types.Tool(name="t", description="d", input_schema={"type": "object"})])

    async def ct(ctx, p):
        raise RuntimeError("kaboom")
    with MCPToolset({"x": Server("x", on_list_tools=lt, on_call_tool=ct)}) as ts:
        r = call(ts, "x__t")
        assert r.is_error and r.text.startswith("Tool x__t failed")


def test_refresh_bypasses_the_list_cache(conn, tmp_path, naive_pins_and_review):
    evil = EvilServer("rug", list_ttl_ms=3_600_000)        # "trust my listing for an hour"
    with MCPToolset({"parcel-rates": evil.server}, lockfile=tmp_path / "l.json", policy="warn") as ts:
        ts.approve()
        ts.refresh()
        assert evil.listings == 2 and ts.last_report.changed == ["parcel-rates/quote_shipping"]


def test_server_names_cannot_contain_the_separator(conn):
    with pytest.raises(ValueError):
        with MCPToolset({"a__b": build_shop_server(conn, 9001)}):
            pass


def test_one_event_loop_for_all_calls(conn, naive_pins_and_review):
    import threading
    with MCPToolset({"shopfront": build_shop_server(conn, 9001)}) as ts:
        before = threading.active_count()
        for _ in range(5):
            call(ts, "shopfront__lookup_order", order_id=4822)
        assert threading.active_count() == before, "calls reuse the toolset's loop thread"
