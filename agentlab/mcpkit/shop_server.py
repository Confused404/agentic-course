"""Shopfront's support tools as an MCP server, for one signed-in customer.

  python -m agentlab.mcpkit.shop_server --customer 9001 [--db data/shopfront.db] [--variant v2]

stdio transport: stdout carries the protocol, so this process must never print to stdout. Logs go to stderr.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import anyio
from mcp.server.lowlevel import Server

from agentlab.assistant.tools import HELP_CENTER, _front_matter, make_support_tools
from agentlab.mcpkit.bridge import Doc, registry_server

INSTRUCTIONS = ("Shopfront customer-support tools for the signed-in customer: orders, refund eligibility, refunds, "
                "cancellations, escalation, and the help center. Amounts are in cents.")


def help_center_docs(root: Path = HELP_CENTER) -> list[Doc]:
    docs = []
    for p in sorted(root.glob("*.md")):
        meta, _ = _front_matter(p.read_text())
        docs.append(Doc(f"help://{p.stem}", p.stem, f"{meta.get('title', p.stem)} ({meta.get('status', '?')}, "
                        f"updated {meta.get('updated', '?')})", p.read_text()))
    return docs


def build_shop_server(conn: sqlite3.Connection, customer_id: int, variant: str = "v2") -> Server:
    # why the customer is fixed at start-up: as in Node 02, the model must not be able to choose whose data it
    # sees. Over stdio, "the signed-in user" is whoever launched the server.
    reg = make_support_tools(conn, customer_id, actor="agent:mcp", variant=variant)
    return registry_server("shopfront", reg, docs=help_center_docs(), instructions=INSTRUCTIONS)


def main(argv: list[str] | None = None) -> int:
    from mcp.server.stdio import stdio_server

    from shopfront import db
    p = argparse.ArgumentParser(prog="python -m agentlab.mcpkit.shop_server")
    p.add_argument("--customer", type=int, required=True)
    p.add_argument("--db", type=Path, default=None)
    p.add_argument("--variant", default="v2")
    a = p.parse_args(argv)
    conn = db.connect(a.db)
    server = build_shop_server(conn, a.customer, a.variant)
    print(f"shopfront MCP server for customer {a.customer} on stdio", file=sys.stderr)

    async def serve():
        async with stdio_server() as (r, w):
            await server.run(r, w, server.create_initialization_options())
    anyio.run(serve)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
