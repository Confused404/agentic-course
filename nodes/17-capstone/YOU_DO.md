# Node 17: your work

Cost: tasks 2–4 and 7 are free; fresh evidence (task 6) ≈ $3–6 on paid models (free models: ≈ 1,500 requests over
several days).

### 1. [PREDICT] (20 min)
Read TEXTBOOK §1–§5 and `config/launch.toml`. Write in `LEARNING_LOG.md`: which of your earlier results would
block a launch today, and which are stale? Which incident will your current alert thresholds miss? What does a
customer see when the model provider is down?

### 2. [AGENT-OFF] stream.py (≤ 1h)
`assemble`; grader `tests/test_stream.py`. First, **[READ-TRACE]**: take the `ANTHROPIC_RAW` events in
`tests/test_launch.py` and write, on paper, the course events they map to and the final response. Then the
unhappy path: a response with two parallel calls, `issue_refund` with fragments `{"order_id": 4822, ` +
`"amount_cents": 4899}` (complete) and `lookup_order` with `{"order_id"` (cut), and no `message_stop`. What do the
two joined texts parse to? Why must *neither* call run, including the one whose JSON is complete?

### 3. [AGENT-OFF] gate.py (≤ 1h)
`launch_decision`; grader `tests/test_gate.py`. Then **[DECIDE]**: write `nodes/17-capstone/launch_policy.toml`
for real. For every threshold, one line in ADR 0014: where the number comes from (a baseline run, a business
constraint, a regulation), and what failure it protects against. Which metrics are blockers and why; what
`max_age_days` you allow and why.

### 4. Delegate, then review (≤ 3h)
`make new-ticket N=17` → coding agent: *"Implement nodes/17-capstone/SPEC.md. Follow AGENTS.md. stream.py and
gate.py are mine; don't write them."*
Review for: the customer id never comes from a request body; tools are filtered by scopes; every failure path
(budget, provider error, max turns, refusal) hands over; a stream that already sent text is never retried; logs
contain no message text or raw customer ids; the kill switch works without calling a model.

### 5. Launch configuration (≤ 1h)
Edit `config/launch.toml` from your Node 15 ADR (model, budget per conversation, max turns) and Node 13 ADR
(scopes). Then try it by hand:
```bash
export LAUNCH_TOKEN_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))") LAUNCH_DEV_TOKENS=1
.venv/bin/python -m agentlab.launch serve
# another terminal
T=$(curl -s -X POST localhost:8001/api/v2/dev/token -H 'content-type: application/json' -d '{"customer_id": 9001}' | python -c "import sys,json; print(json.load(sys.stdin)['token'])")
S=$(curl -s -X POST localhost:8001/api/v2/session -H "Authorization: Bearer $T" | python -c "import sys,json; print(json.load(sys.stdin)['session_id'])")
curl -N -X POST localhost:8001/api/v2/stream -H 'content-type: application/json' -d "{\"session_id\": \"$S\", \"message\": \"Where is order 4822?\"}"
```
(Customer 9001 must be in your rollout: set `percent = 100` while testing, or pick a customer that is. Every
`chat`/`stream` call needs the same `-H "Authorization: Bearer $T"` header: add it to the last command.) **[LOG]**
time to first `delta` vs time to `done`. Then flip `kill_switch = true` in `config/launch.toml` *without
restarting* and time how long it takes to take the assistant away from everyone, including the open session. Then
make the bad tokens yourself and try them:
```bash
.venv/bin/python -c "
import os, time; from agentlab.authz.tokens import issue_token
s = os.environ['LAUNCH_TOKEN_SECRET'].encode(); now = int(time.time())
print(issue_token(s, sub='customer:9001', audience='shopfront-mcp', scopes=['orders:read'], now=now, customer_id=9001))
print(issue_token(s, sub='customer:9001', audience='shopfront-assistant', scopes=['orders:read'], now=now - 3600, customer_id=9001))
print(issue_token(s, sub='customer:9001', audience='shopfront-assistant', scopes=['tickets:write'], now=now, customer_id=9001))
print(issue_token(s, sub='customer:9002', audience='shopfront-assistant', scopes=['orders:read'], now=now, customer_id=9002))"
```
(other audience, expired, missing scope, and another customer trying your session id). Note what the logs contain.

### 6. Fresh evidence and the gate (≤ 1 day, mostly waiting; ≈ $3–6)
Run, on your launch configuration (a plain alias with prompt and tools v2, which is what the launch service runs;
if your Node 15 choice was a cascade or a cache layout, either add it to the service first or measure the plain
alias you'll actually ship):
```bash
.venv/bin/python -m agentlab.evals run --suite nodes/04-evals/evals/support --split all --models fast --trials 3 \
  --prompt v2 --tools v2
.venv/bin/python -m agentlab.perf bench --configs fast --human-cost <yours>
.venv/bin/python -m agentlab.security attack ...       # your chosen defence (Node 08 YOU_DO)
.venv/bin/python -m agentlab.reliability chaos --model fast --configs naive,durable   # if the chaos rule is a blocker
.venv/bin/python -m agentlab.launch scorecard --evals runs/evals/<dir> --evals-model fast --perf runs/perf/<dir> \
  --security runs/security/<dir> --security-defense <d> --chaos runs/reliability/<dir> --chaos-config naive
.venv/bin/python -m agentlab.launch gate
```
(`--chaos-config`: the configuration matching what you launch. The service as built has no durable refunds, so
`naive` is the honest one, unless you add Node 14's runner.)
**[LOG]** the verdict. If it's NO-GO: fix and re-measure, or change the policy and say in the ADR exactly why that
isn't moving the goalposts. If it's GO: what would have to be true for it to be wrong?

### 7. The drill, alerts and the runbook (≤ 3h, free)
```bash
.venv/bin/python -m agentlab.launch drill
```
The drill runs your `config/launch.toml` (everyone in the rollout) against fake models on a simulated clock. Tune
`[alerts]` in the policy until every incident fires within 10 simulated minutes and normal traffic never does. Then add a phase of your own to `default_phases()` (a cost blow-up: a model that answers correctly but with
50,000-token prompts; or slow responses) and make an alert catch it. **[LOG]** each threshold's margin over normal
traffic. Write `docs/RUNBOOK.md`: per alert, what it means, the first three checks, the safe actions (kill switch,
roll back the prompt, switch the alias), who owns it, and the postmortem trigger.

### 8. Launch review by a separate agent (≤ 1h)
Give a fresh coding-agent session (no access to this conversation; Node 12's evaluator principle) the repo, your
ADRs, the scorecard and the runbook, and ask: *"You are the launch reviewer for this support assistant. Find the
three most likely ways it fails customers in week one, and check whether the evidence and the runbook cover each.
Don't change code."* **[LOG]** its findings, which you agree with, and what you change.

### 9. [DECIDE] ADR 0014 and a retrospective (≤ 1.5h)
`docs/adr/0014-launch.md`: the configuration, the policy and its thresholds, the gate verdict, what's deliberately
not in launch day (durable refunds? memory? the cascade?) and when it would be, the week-one watch list, and the
criteria for 10% → 50% → 100%. Then a one-page course retrospective in `LEARNING_LOG.md`: your earliest predictions
against what you measured; the three decisions you'd now make differently; the parts you'd keep homemade and the
parts you'd buy.
