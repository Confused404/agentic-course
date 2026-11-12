# Node 13 cheat sheet: permissions and authorization

**Four questions**: who is acting (authN) · on whose behalf/what data (principal bound at issue) · which permissions
(scopes) · is this action OK now (gate). All four, independently.

**Gate v2 (unattended)**: rules (allow/deny/ask) → classifier for "ask" (policy + task + action only; action is
data; n parallel votes; allow only above threshold; failures = block) → escalate to a human after repeated denials.
Measure: false positives (friction), misses (incidents), per category, % by rules, $/1k decisions, latency.

**Least privilege**: scopes filter tools at listing AND call time; unknown tools never exposed; the customer comes
from the verified token, never from arguments (confused deputy).

**verify_token checks**: 3 base64url parts → alg exactly from your list, before using the key → HMAC over the bytes
received, constant-time → typed claims → exp/nbf (+ leeway) → exact audience → scopes ⊆ granted. Never pass tokens
through to another service.

**MCP auth (HTTP)**: server = OAuth 2.1 resource server; Protected Resource Metadata; clients send `resource` (RFC
8707) → audience-bound tokens; 401 invalid, 403 `insufficient_scope` with required scopes; stdio servers use env
credentials instead.

**Red team**: per blocked category, find routes the rules don't name; add misses to the labelled set; re-measure FP.

`python -m agentlab.authz gate-eval --methods rules:block,two-stage:fast:3:1.0`
`python -m agentlab.authz token-issue --sub customer:9001 --cid 9001 --scopes orders:read`
