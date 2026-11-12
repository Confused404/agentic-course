# Appendix (dated 2026-11): permissions and authorization in practice

## Classifier gates in coding agents
- **Claude Code auto mode** (introduced March 2026; check `code.claude.com/docs/en/permission-modes` for which plans
  and versions start in it by default): a separate classifier reviews tool calls instead of prompting the user. It
  reads the user's messages, project instructions (CLAUDE.md) and the proposed tool calls, with tool results stripped;
  a separate probe screens tool results for prompt injection. Read-only tools and edits inside the project skip the
  classifier; the classifier itself runs in two stages (a fast filter that leans towards blocking, then a slower
  reasoning pass on what it flags), which differs from this node's rules-then-classifier design. When it blocks,
  Claude is told to find another approach; after 3 consecutive blocks or 20 in a session it falls back to asking the
  user (in headless `-p` runs the blocked action simply isn't run). Anthropic's post publishes rates you can compare
  with yours: about 0.4% false positives, and false-negative rates of about 17% on real over-eager actions and 5.7%
  on synthetic exfiltration attempts. It also reports that users accepted about 93% of permission prompts, the
  approval fatigue that motivated it.
  https://www.anthropic.com/engineering/claude-code-auto-mode · docs: https://code.claude.com/docs/en/permission-modes
- **OpenCode**: per-tool and per-command `permission` settings (`allow`, `ask`, `deny`, with glob patterns for bash
  commands) in `opencode.json`, globally or per agent. https://opencode.ai/docs/permissions/

## MCP authorization (spec revision 2026-07-28)
https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization
- Optional; for HTTP transports. **stdio servers SHOULD NOT use it** and take credentials from the environment.
- The MCP server is an **OAuth 2.1 resource server**; it MUST publish **Protected Resource Metadata** (RFC 9728),
  which tells clients where its authorization server is. 401 responses carry a `WWW-Authenticate` header pointing at
  that metadata and SHOULD include the required `scope`.
- Clients obtain a client id by **Client ID Metadata Documents** (preferred; the client id is an HTTPS URL to a JSON
  document), pre-registration, or Dynamic Client Registration (deprecated). They use PKCE, send the **`resource`
  parameter** (RFC 8707: the server's canonical URI) in authorization and token requests, and validate the
  authorization response's `iss` (RFC 9207) against the issuer they recorded.
- Tokens go in the `Authorization: Bearer` header on every request, never in the URL. Servers MUST validate that a
  token was issued for them (audience) and **MUST NOT accept or pass through other tokens**.
- Runtime scope failures: **403** with `error="insufficient_scope"` and the scopes needed; clients may step up
  (re-authorize with the union of old and new scopes), with retry limits.

## Token formats
JWT/JWS (RFC 7519/7515). Production resource servers usually verify asymmetric signatures (RS256/ES256/EdDSA) with
keys from the issuer's JWKS endpoint, cache keys, and check `iss`, `aud`, `exp`, `nbf` and scopes. Libraries:
PyJWT, joserfc, authlib. Classic pitfalls are the ones your tests cover: `alg: none`, algorithm confusion
(verifying an HMAC with a public key as the secret), missing audience checks, and non-constant-time comparison.

## Agent identity
Emerging practice gives agents their own identities (workload or service identities) and short-lived,
narrowly-scoped, audience-bound tokens obtained per task (token exchange, RFC 8693), instead of long-lived user or
admin credentials in the agent's environment.
