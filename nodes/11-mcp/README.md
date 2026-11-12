# Ticket MCP-11: "Ship Shopfront's tools as an MCP server, and decide which third-party servers we allow"

| | |
|---|---|
| **Estimate** | 1.5 days |
| **Cost cap** | ≈ $0.10–0.20 for the full lab on `fast` (64 short runs); `tools` and the tests are free. On free OpenRouter models: ≈ 260 requests for the full lab (see YOU_DO 6 for a ≈ 30-request subset) |
| **Prerequisites** | Node 02 (loop, ToolExecutor), Node 05 (tool design), Node 08 (prompt injection, flow policy) |
| **You will touch** | `agentlab/mcpkit/pins.py`, `review.py` (yours); bridge, server, client, lab, CLI (agent); your coding agents' MCP config; `docs/adr/0008-*` |
| **Done when** | `make grade N=11` green · Shopfront server working in Claude Code AND OpenCode · lab grid read and explained · ADR 0008 |

## Story
Two requests landed on the same day. Support engineering wants Shopfront's tools available in the coding agents
everyone already uses, so they can debug customer issues without copy-pasting. And someone wants to connect a
third-party "parcel-rates" server to the support agent for shipping quotes. You'll do the first properly, and find
out what the second would cost before anyone says yes.

## Deliverables
1. `agentlab/mcpkit/pins.py`: tool-definition fingerprints, lockfile diffs, collisions: **by hand** (AGENT-OFF).
2. `agentlab/mcpkit/review.py`: a reviewer for tool metadata: **by hand** (AGENT-OFF).
3. Bridge, Shopfront server, multi-server client, lab, CLI: coding agent, from `SPEC.md`.
4. Your server configured in both coding agents, with notes on how each presents and approves it.
5. The lab grid, with every non-obvious cell explained from a transcript.
6. `docs/adr/0008-mcp-admission.md`: the policy for admitting third-party servers.

## Time boxes
| Step | Box | Escape hatch |
|---|---|---|
| TEXTBOOK + predictions | 1.5h | |
| pins.py | 1h | `git show solution/node-11:agentlab/mcpkit/pins.py` |
| review.py | 1h | same, `review.py` |
| Agent builds SPEC + review | 2h | `make solution N=11` |
| Coding agents + `tools` | 1h | one agent only |
| Lab | 1.5h | the subset in YOU_DO 6 |
| ADR | 30m | |

## Rubric (0–2 each)
| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Pins & review | tests fail | tests pass | + your reviewer's false positives/negatives on real servers discussed |
| Integration | server doesn't load | works in one agent | works in both; naming, approval and token cost compared |
| Lab | not run | grid produced | every harm/utility trade-off explained from transcripts |
| Policy | "don't use MCP" / "it's fine" | rules listed | a policy with an owner, pinning, re-review triggers, least privilege and data-flow limits |
