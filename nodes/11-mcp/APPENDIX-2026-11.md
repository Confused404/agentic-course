# Appendix (dated 2026-11): MCP specifics

## Spec revision 2026-07-28 (current as of this writing)
The changelog lists these major changes since 2025-11-25 (https://modelcontextprotocol.io/specification/2026-07-28/changelog):
- **Stateless protocol.** No `initialize` handshake and no protocol-level sessions (`Mcp-Session-Id` is gone).
  Every request carries its protocol version and client capabilities in `_meta`; servers must implement
  `server/discover` (versions, capabilities, identity). Cross-call state uses explicit server-minted handles passed as
  ordinary tool arguments.
- **Multi round-trip requests.** Instead of the server sending requests to the client (sampling, elicitation, roots),
  a tool call can return an `input_required` result; the client retries the original request with the answers.
  Every result now has `resultType` (`complete` or `input_required`).
- **Subscriptions** (`subscriptions/listen`) replace the HTTP GET stream and resource subscribe/unsubscribe.
- **Removed**: `ping`, `logging/setLevel`, SSE resumability. **Deprecated**: Roots, Sampling and Logging (pass
  paths as parameters, call model APIs directly, log to stderr / OpenTelemetry), the old HTTP+SSE transport, and
  Dynamic Client Registration in favour of Client ID Metadata Documents (Node 13).
- **Minor but relevant to this node**: servers SHOULD return `tools/list` in a deterministic order (prompt caching);
  list/read results carry `ttlMs` and `cacheScope` caching hints; tool schemas may use any JSON Schema 2020-12
  keywords; tasks moved into an official extension; OpenTelemetry trace context may ride in `_meta`.
- A feature lifecycle policy now guarantees at least twelve months between deprecation and removal.

Hosts and servers negotiate: clients probe `server/discover` and fall back to the old handshake for older servers.
Code in this node works with both because the SDK handles it.

## Python SDK (mcp 2.x)
- `mcp==2.3.0` is pinned. v2 renamed the high-level `FastMCP` to `mcp.server.mcpserver.MCPServer`; importing
  `mcp.server.fastmcp` raises an error pointing at the migration guide (https://py.sdk.modelcontextprotocol.io/v2/migration/).
- This node uses the low-level `mcp.server.lowlevel.Server(name, on_list_tools=..., on_call_tool=...)`, because the
  bridge must publish your own JSON Schemas verbatim (the decorator API derives schemas from Python signatures).
- `mcp.Client(target)`: target may be a URL (Streamable HTTP), `StdioServerParameters`, a transport, or a server
  object (in-process, for tests). `mode="auto"` probes `server/discover`, `"legacy"` forces the handshake. The
  client caches list results according to `ttlMs` by default.
- Unexpected exceptions inside high-level tools come back as a generic "Error executing tool …": raise the SDK's
  `ToolError` (or, with the low-level server, return an error result) with an actionable message.

## Coding agents
- **Claude Code**: `claude mcp add [--scope local|project|user] <name> -- <command> [args…]` (stdio is the default;
  `--transport http <name> <url>` for remote). Local scope (the default) lives in `~/.claude.json` under the project
  path; project scope writes `.mcp.json` at the repo root (shared via git; each user approves project servers on
  first use); user scope is global. Precedence: local > project > user. `claude mcp list` shows connection status;
  `/mcp` inside a session manages servers and OAuth. Model-facing names look like `mcp__<server>__<tool>`.
  Tool search is on by default: MCP tool definitions are deferred and discovered on demand once they exceed a
  context threshold (`ENABLE_TOOL_SEARCH=auto:<percent>` or `false`; `alwaysLoad: true` per server in `.mcp.json`).
  Docs: https://code.claude.com/docs/en/mcp
- **OpenCode**: `"mcp": {"<name>": {"type": "local", "command": [...], "environment": {...}, "enabled": true}}` or
  `{"type": "remote", "url": ..., "headers": {...}}` in `opencode.json`. Tools are prefixed with the server name;
  disable globally with globs (`"tools": {"shopfront_*": false}`) and re-enable per agent. The docs warn that MCP
  servers add to context and some (e.g. GitHub's) can exceed it. Docs: https://opencode.ai/docs/mcp-servers/

## Supply-chain research
- Invariant Labs named **tool poisoning** in April 2025 (hidden `<IMPORTANT>` instructions in an innocuous tool's
  description), and demonstrated **rug pulls** (definitions changing after approval) and **shadowing** (one server's
  description changing how the agent uses another server's tool, e.g. redirecting a trusted email tool).
  https://invariantlabs.ai/blog/mcp-security-notification — their open scanner (MCP-Scan)
  pins tool definitions and flags cross-server references.
- OWASP's MCP Top 10 lists tool poisoning (alongside rug pulls and shadowing) as a named risk class; a 2025 CVE
  (CVE-2025-54136) showed tool approval in a production IDE not surviving later server-side changes: a rug pull.
- Practice targets: "Damn Vulnerable MCP Server" (DVMCP) and similar deliberately vulnerable server collections.

## A2A (agent-to-agent), one page
Google announced A2A in April 2025; it moved to the Linux Foundation in June 2025 and to the Agentic AI Foundation
(which also hosts MCP) in August 2026. **v1.0** (2026) is the current stable spec. An agent publishes an **agent
card** at `/.well-known/agent-card.json` (name, description, version, supported interfaces, capabilities, skills,
security schemes; v1.0 adds signed cards). Clients `SendMessage` (or stream), and work is tracked as a **task**
moving through states such as working and input-required, producing **artifacts**. Credentials travel in HTTP
headers. https://a2a-protocol.org/latest/ — elective E4 builds a small A2A agent and client.
