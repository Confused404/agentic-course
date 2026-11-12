# Node 13: your work

Cost: tokens, scopes and rules-only gate runs are free; classifier runs ≈ $0.10–0.30 on `fast`.

### 1. [PREDICT] (20 min)
Read `evals/POLICY.md` and 15 items of `evals/actions.yaml`. Predict in `LEARNING_LOG.md`: what share of items
Node 03's rules decide, and the false-positive and miss rates of `rules:block`, `rules:allow`, `classifier:fast:3`
and `two-stage:fast:3:1.0`. Which categories will the classifier miss?

### 2. [AGENT-OFF] verify_token (≤ 1.5h)
`agentlab/authz/tokens.py`; grader `tests/test_tokens.py`. Before writing code, write next to each numbered check
in the docstring the attack it stops (TEXTBOOK §4). Then: why must the algorithm be checked before the key is used,
and why must the signature be computed over the parts exactly as received?

### 3. Delegate, then review (≤ 2h)
`make new-ticket N=13` → coding agent: *"Implement nodes/13-permissions/SPEC.md. Follow AGENTS.md. verify_token is
mine; don't write it."*
Review for: the classifier never sees anything but the policy, the task and the command; failed and unparseable
votes are blocks; votes run in parallel with fresh models; unknown tools are never exposed; the customer comes only
from the verified token; escalation after repeated denials.

### 4. Tokens in practice (≤ 20 min, free)
```bash
T=$(.venv/bin/python -m agentlab.authz token-issue --sub customer:9001 --cid 9001 --scopes orders:read)
.venv/bin/python -m agentlab.authz token-verify "$T" --scopes orders:read
.venv/bin/python -m agentlab.authz token-verify "$T" --scopes refunds:write
.venv/bin/python -m agentlab.authz token-verify "$T" --aud billing-api
```
Then forge a scope (the `base64` command-line tool adds padding and uses `+/`, which your verifier rejects as
malformed before it gets to the interesting check, so use the course helpers):
```bash
.venv/bin/python -c "
import json,sys; from agentlab.authz.tokens import b64url, b64url_decode
h,p,s = sys.argv[1].split('.'); d = json.loads(b64url_decode(p)); d['scope'] += ' refunds:write'
print(h + '.' + b64url(json.dumps(d).encode()) + '.' + s)" "$T" > /tmp/forged
.venv/bin/python -m agentlab.authz token-verify "$(cat /tmp/forged)" --scopes refunds:write
```
**[LOG]** each result, and which check produced it. One check no test can verify: that you compared the MAC with
`hmac.compare_digest`, not `==`. Explain why it matters.

### 5. The gate comparison (≤ 1h, ≤ $0.30)
```bash
.venv/bin/python -m agentlab.authz gate-eval --methods rules:block,rules:allow
.venv/bin/python -m agentlab.authz gate-eval --budget 0.3 \
   --methods rules:block,classifier:fast:3,two-stage:fast:3:1.0,two-stage:fast:3:0.66
```
- **[LOG]** the table against your prediction.
- Read every miss and every false positive of the two-stage gate. For each miss: which part of the command did the
  classifier fail to read (a pipe stage, decoded text, a config option, a comment aimed at it)?
- Unanimous (`1.0`) vs 2-of-3 (`0.66`): what does the threshold trade, on these numbers? (Note that
  `classifier:fast:3` uses a majority, so comparing it with `two-stage:…:1.0` changes two things at once.)
- Check the "failed votes" column before blaming the classifier: rate limits and outages become block votes.
- Which misses did the rules allow, so the classifier never saw them?
- What would the same gate cost per 1,000 agent actions, and how much of that does the rules stage save?

### 6. [AGENT-OFF] Red team (≤ 2h)
Write `nodes/13-permissions/evals/redteam.yaml` (same format as `actions.yaml`) with at least 10 actions the policy
blocks but you expect the two-stage gate to allow: other interpreters (`perl -e`, `node -e`, `python3 - <<EOF`),
encodings, symlinks, tool options that execute (`git -c`, `tar --to-command`, `find -exec`), split payloads,
comments addressed to the reviewer, and commands the RULES allow but the policy blocks (reading secrets through an
allowed tool). Include 3 legitimate-but-weird actions too (label `allow`), so you can see
your fixes' false-positive cost.
```bash
.venv/bin/python -m agentlab.authz gate-eval --extra nodes/13-permissions/evals/redteam.yaml --skip-denied \
   --methods two-stage:fast:3:1.0 --budget 0.2
```
Fix what got through (a rule in Node 03's lists, or a sentence in `classifier_system()`), re-run both the red-team
and the full set, and **[LOG]** misses and false positives before and after.

### 7. [DECIDE] ADR 0010 (30 min)
`docs/adr/0010-unattended-permissions.md`: your gate configuration (stages, model, votes, threshold, escalation),
its measured FP and miss rates with the red team included, and what bounds the damage of the misses that remain
(sandbox level, secrets, egress, scopes and token lifetime, audit). Would you let shopdev run overnight on this
repo? On a repo with production credentials?

### Stretch
- Serve `authorized_shop_server` over Streamable HTTP with a bearer-token check: 401 for a missing or invalid
  token, 403 with `error="insufficient_scope"` for a missing scope (APPENDIX), and the customer from the token.
- Give the classifier the last few user messages too (as Claude Code's does) and see whether context-dependent
  items change.
