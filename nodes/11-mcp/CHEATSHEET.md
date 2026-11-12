# Node 11 cheat sheet: MCP

**Parts**: host → one client per server → server. **Primitives**: tools (model picks) · resources (host/app picks)
· prompts (user picks). **Transports**: stdio (local child process; stdout = protocol, log to stderr) · Streamable
HTTP (remote; needs auth). JSON-RPC underneath; dated spec revisions.

**Invariants**: tools = name + description + JSON Schema; results = content + isError; the model reads metadata as
instructions; annotations are hints, never guarantees; the host owns consent.

**Serving**: thin bridge over your registry: same names, schemas, errors (Node 05 carries over). Honest annotations.
Identity fixed at start-up (stdio) or by auth (HTTP), never chosen by the model.

**Consuming**: namespace (`server__tool`) · allowlist per task · validate args client-side · errors as data · re-list
and diff · count definition tokens (they ride on every request).

**Supply chain**: poisoning (description instructs) · shadowing (rewrites other servers' tools; look-alikes) · rug
pull (changes after approval) · poisoned results (Node 08). **Defenses**: least privilege · namespaces · pin
(fingerprint name+description+schema+annotations) + human review · flow policy · write approval. Sandboxing the
server process does NOT stop metadata attacks.

**Measure**: harm AND utility, per attack × defense; include an obedient model.

**MCP vs A2A**: agent ↔ tools (MCP) · agent ↔ agent, opaque, tasks + agent cards (A2A).

`claude mcp add --scope local shopfront -- "$PWD/.venv/bin/python" -m agentlab.mcpkit.shop_server --customer 9001 --db /tmp/shop-mcp.db`
`python -m agentlab.mcpkit tools --mode rug --listing 2` · `python -m agentlab.mcpkit lab --model fast`
