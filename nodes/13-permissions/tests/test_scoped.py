
import anyio
import pytest
from mcp import Client

from agentlab.authz.scoped import ScopedExecutor, authorized_shop_server, scoped_registry, shop_tools_for_token
from agentlab.authz.tokens import Principal, TokenError, issue_token
from agentlab.llm.types import ToolUseBlock

K = b"k" * 32
NOW = 1_800_000_000


def tok(scopes, cid=9001, **kw):
    return issue_token(K, sub=f"customer:{cid}", audience="shopfront-mcp", scopes=scopes, now=NOW, customer_id=cid,
                       **kw)


def test_read_only_token_sees_no_write_tools(conn, naive_verify):
    ex, p = shop_tools_for_token(conn, tok(["orders:read"]), K, now=NOW)
    names = {s.name for s in ex.specs()}
    assert names == {"search_help_center", "get_my_orders", "lookup_order", "check_refund_eligibility"}
    r = ex.execute(ToolUseBlock("1", "issue_refund", {"order_id": 4822, "amount_cents": 100, "reason": "damaged"}))
    assert r.is_error and "refunds:write" in r.text, "refused at call time too, with the missing scope named"


def test_customer_comes_from_the_token(conn, naive_verify):
    ex, p = shop_tools_for_token(conn, tok(["orders:read"], cid=9002), K, now=NOW)
    mine = ex.execute(ToolUseBlock("1", "lookup_order", {"order_id": 4822}))
    assert mine.is_error, "order 4822 belongs to 9001: a 9002 token can't see it"
    with pytest.raises(TokenError):
        shop_tools_for_token(conn, issue_token(K, sub="agent:x", audience="shopfront-mcp", scopes=["orders:read"],
                                               now=NOW), K, now=NOW)


def test_unknown_tools_are_never_exposed(conn):
    from agentlab.assistant.tools import make_support_tools
    from agentlab.tools.base import Tool
    reg = make_support_tools(conn, 9001).with_tools([Tool("drop_tables", "x", {"type": "object"}, lambda: 1)])
    p = Principal("x", 9001, frozenset({"orders:read", "orders:write", "refunds:write", "tickets:write"}), "a", 0)
    assert "drop_tables" not in scoped_registry(reg, p).names()
    assert ScopedExecutor(reg, p).execute(ToolUseBlock("1", "drop_tables", {})).is_error


def test_mcp_listing_depends_on_the_token(conn, naive_verify):
    async def names(server):
        async with Client(server) as c:
            return {t.name for t in (await c.list_tools()).tools}
    full = anyio.run(names, authorized_shop_server(conn, tok(["orders:read", "refunds:write"]), K, now=NOW))
    ro = anyio.run(names, authorized_shop_server(conn, tok(["orders:read"]), K, now=NOW))
    assert "issue_refund" in full and "issue_refund" not in ro


def test_the_real_verifier_is_called_with_this_audience(conn, monkeypatch):
    from agentlab.authz import tokens as T
    seen = {}

    def spy(token, secret, *, audience, required_scopes=frozenset(), now, leeway_s=0):
        seen["audience"] = audience
        raise TokenError("bad_signature")
    monkeypatch.setattr(T, "verify_token", spy)
    with pytest.raises(TokenError):
        shop_tools_for_token(conn, tok(["orders:read"]), K, now=NOW)
    assert seen["audience"] == "shopfront-mcp"


def test_expired_sessions_stop_working(conn, naive_verify):
    from agentlab.assistant.tools import make_support_tools
    p = Principal("customer:9001", 9001, frozenset({"orders:read"}), "shopfront-mcp", expires_at=100)
    ex = ScopedExecutor(make_support_tools(conn, 9001), p, clock=lambda: 100)
    r = ex.execute(ToolUseBlock("1", "lookup_order", {"order_id": 4822}))
    assert r.is_error and "expired" in r.text
