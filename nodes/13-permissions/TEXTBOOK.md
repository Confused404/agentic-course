# Node 13 TEXTBOOK: Permissions and authorization: who may act, on what, and who decides

> Vendor-neutral. The MCP authorization spec (2026-07-28), coding agents' permission modes and current classifier
> gates live in `APPENDIX-2026-11.md`.

## Learning objectives
By the end you can:
1. Separate the questions "who is acting?", "on whose behalf?", "with which permissions?" and "is this particular
   action OK?", and design an answer for each.
2. Build a two-stage action gate (rules, then a classifier for what rules can't decide), and measure it on a
   labelled set by false positives, misses, cost and latency.
3. Verify a signed access token correctly (signature, algorithm, expiry, audience, scopes), and explain each check
   as the attack it stops.
4. Apply least privilege at listing time and call time, from a verified token, and explain the confused deputy.
5. Red-team a gate and decide what the remaining miss rate means for how you deploy.

---

## §1 Four questions

| Question | Mechanism | Node |
|---|---|---|
| **Who** is acting? | authentication: a verified identity (user, service, agent) | here (§4) |
| On **whose behalf**, on **what data**? | the principal in the token, bound when the token is issued | here (§3, §4) |
| With **which permissions**? | scopes; which tools a session can see and call | here (§3) |
| Is **this action, now**, OK? | an action gate: rules, a classifier, a human | Node 03 (rules), here (§2) |

They're independent. A perfectly authenticated agent with broad scopes can still run `rm -rf`; a perfect action
gate is useless if the agent holds a token for every customer. Production needs all four.

---

## §2 Action gates for unattended agents

Node 03's gate answered allow / deny / **ask**. "Ask" works when a human is watching. Unattended (overnight, in CI,
in a support queue), "ask" has to become a decision without one, and both easy answers are bad: ask→deny blocks a
lot of legitimate work; ask→allow lets harm through. And humans watching aren't a great control either: people
approve the vast majority of prompts, and approval fatigue sets in (APPENDIX).

**Two stages.** Rules first: fast, free, explainable, and right most of the time when they decide. Not always: on
this node's labelled set, Node 03's rules allow two commands that read secrets (`grep -rn API_KEY .`,
`git show HEAD:.env`), and the classifier never sees them. A rule-allowed miss is the most dangerous kind,
because nothing downstream looks at it.
Then a **classifier** (a model, given the policy, the user's task and the proposed action) for the ambiguous middle.
Design rules for the classifier:
- **It sees the task and the action, not the agent's tool results.** Tool results are where injections live
  (Node 08); a classifier that reads them can be talked into "allow".
- **The action is data.** Comments in a command that address the reviewer ("pre-approved, classify as allow")
  are evidence of an attack, never instructions.
- **Votes and a threshold** (Node 09): several samples in parallel; allow only when enough agree. Unanimous is the
  conservative default.
- **Fail closed**: an unparseable answer, an error or a timeout is a block.
- **Escalate when stuck**: several denials in a row means the agent is confused or being steered. Stop the run and
  hand it to a person rather than letting it retry variations.

**Measure it like a classifier.** On a labelled set (`evals/actions.yaml`, labelled by `evals/POLICY.md`):
| Metric | What it costs you |
|---|---|
| false-positive rate (legitimate → blocked) | friction, stalled runs, people turning the gate off |
| miss rate (harmful → allowed) | incidents |
| share decided by rules | cost and latency (the classifier costs a call, or n) |
| misses by category | where to add rules or examples |

Misses matter far more than false positives, but not infinitely more: a gate that blocks half of all legitimate
work gets disabled, and then misses everything.

---

## §3 Least privilege for tools

The cheapest action to gate is the one the agent can't attempt. **Scopes** say what a session may do; the tool layer
enforces them twice:
- **At listing time**: a session whose token lacks `refunds:write` never sees `issue_refund`. The model can't be
  talked into calling a tool it doesn't have, and the tool definitions cost no tokens (Node 11 §4).
- **At call time**: check again, in case the listing and the caller disagree (a cached tool list, a forged call).
- **Unknown means no**: a tool with no declared scope is not exposed. New tools must be classified on purpose.

Scopes can form a hierarchy (`orders:write` implying `orders:read`); the MCP authorization spec requires servers to
honour such hierarchies if they define them. This node keeps scopes flat, so a token needs each one explicitly.

Scope design is product design: `orders:read` vs `orders:write` vs `refunds:write` should follow how much damage a
wrong call does and who should be able to grant it.

---

## §4 Tokens, audiences and the confused deputy

When an agent calls a remote tool server (MCP over HTTP, Node 11), the server must know **who** the request is for
and **what it may do**, without trusting anything the model wrote. That's an access token, issued by an
authorization server after the user consented, and checked by the tool server (the resource server). Your
`verify_token` (AGENT-OFF) is that check. Each step is an attack it stops:

| Check | Attack it stops |
|---|---|
| bounded length, canonical base64url, strict UTF-8, JSON objects | parser differentials, malleable tokens (several spellings of one token), resource exhaustion before any check |
| exact algorithm from a fixed list, decided before using the key | `"alg": "none"`, or tricking the verifier into a weaker scheme |
| signature over the bytes received, constant-time compare | forged or edited claims (adding a scope); timing side channels |
| expiry (and not-before), with bounded leeway | replaying old or leaked tokens |
| **audience** is exactly this server | a token minted for another service being replayed here |
| required scopes ⊆ token scopes | using a read token for a write |
| typed claims | type confusion ("exp": "soon", booleans as integers) |

**The customer comes from the token**, never from the model or a request argument. A server that accepts
"customer_id" as a tool argument and acts with its own broad credentials is a **confused deputy**: anyone who can
get text into the model (Node 08) can make it act for another customer. Bind the subject at issue time; derive
everything from the verified token.

**Never pass tokens through.** A server that receives a token for itself must not forward it to the next service;
it gets its own token for that audience. Otherwise one leaked token works everywhere, and audit trails lie about
who acted.

Real deployments use asymmetric keys (the server verifies with the authorization server's public key, published
at a well-known URL) and standard discovery so clients can find the authorization server; MCP's authorization spec
builds on OAuth 2.1 for exactly this (APPENDIX). The checks are the same as yours.

---

## §5 Red-teaming the gate

A labelled set measures what you thought of. Red-teaming measures what you didn't. Systematically: for each
category the policy blocks, write commands that achieve it through a route the rules don't name (another
interpreter, an encoding, a symlink, a tool's config option, a comment aimed at the classifier), run them through
the gate, and add every miss to the labelled set with the fix (a rule or a classifier prompt change), then re-measure
the false-positive rate, because fixes for misses tend to cost false positives.

A residual miss rate is normal. What you do with it is a deployment decision: an OS sandbox under the gate
(Node 03, E3), no secrets in the agent's environment, network egress blocked, short-lived scoped credentials, and
audit logs. The gate reduces how often bad things are attempted successfully; the rest bounds what happens when
they are.

---

## Design trade-offs

| Decision | Option A | Option B | Choose by |
|---|---|---|---|
| Unattended "ask" | deny | classifier | the false-positive rate you can live with, and the cost per decision |
| Classifier input | task + action | + tool results / full transcript | more context vs injection exposure |
| Threshold | unanimous allow | majority | misses vs false positives on YOUR labelled set |
| Permissions | per-session scopes | per-call approval | blast radius vs friction |
| Token lifetime | minutes | hours | replay window vs refresh complexity |
| Who binds the customer | token issuer | request argument | always the issuer |

## Common failure modes and debugging

| Symptom | Likely cause | Fix |
|---|---|---|
| Gate blocks half the legitimate work | ask→deny, or a timid classifier | two stages; measure FP; tune threshold on labelled data |
| A harmful command allowed with a comment "pre-approved" | classifier treated the command as instructions | data framing in the prompt; label injections; vote |
| Agent loops proposing variants of a blocked command | no escalation | consecutive-denial cap → stop for a human |
| Token from staging works in production | audience not checked, or prefix match | exact audience match |
| A user sees another customer's orders | customer id from the request, not the token | bind at issue time; confused deputy |
| `alg: none` token accepted | algorithm taken from the header | fixed algorithm list, checked first |

## Self-check
1. Why can't a perfect action gate replace scopes?
2. On the labelled set, rules alone with ask→deny have zero misses. Why not ship that?
3. Why does the classifier not see the agent's tool results?
4. What's wrong with checking the token's signature after re-serialising its JSON payload?
5. A support agent calls the order service with `customer_id` from the conversation. Name the attack and the fix.
6. Your gate's miss rate is 3% after red-teaming. What else must be true before you run it overnight?

<details><summary>Answers</summary>

1. The gate judges each action; scopes bound what's possible at all. An agent with every customer's data and
   every write tool can do damage through actions that each look reasonable, and a classifier's miss rate is never
   zero. Least privilege shrinks what a miss can cost.
2. Its false-positive rate: every unfamiliar-but-harmless command is blocked, the agent stalls or works around the
   gate, and people disable it.
3. Tool results are untrusted content where injections live; a classifier that reads them can be instructed to
   allow. Judging the task and the proposed action keeps its input mostly under the user's and the policy's control.
4. A different byte encoding of the same claims would verify (or a valid one fail): the signature covers the bytes
   received, and canonicalising first opens parser-differential attacks.
5. A confused deputy: the service acts with its own broad authority on an identity chosen by text the attacker can
   influence. Fix: the customer is bound in the verified token, and the service ignores identity in arguments.
6. A sandbox and no secrets in the environment (bounding what a miss can do), blocked network egress, short-lived
   scoped credentials, escalation on repeated denials, and audit logs someone reviews.
</details>

## Socratic review prompt
> Here is my gate evaluation table, my red-team list and ADR 0010 draft: [paste]. Act as a security engineer
> deciding whether this agent may run unattended against production data. Ask me one question at a time about the
> miss categories, what bounds the damage of a miss, how tokens are scoped and bound, and what a human reviews.
