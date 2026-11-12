# Node 12 cheat sheet: harness engineering

**Harness** = loop + tools + gate + context policy + state between sessions + who decides "done" + hooks + skills.
Same model, different harness: big differences. Stronger model: some pieces become dead weight. Re-measure.

**One long session fails by**: premature "done" · self-evaluation bias · context exhaustion/drift · test tampering ·
no recovery point.

**State outside the context**: progress file (JSON: id, title, status, attempts, notes) · git commit per passed
session, reset failed attempts · one feature per fresh session · an outer loop in plain code (the "Ralph" loop) ·
validate the agent's edits to the progress file (only the harness counts attempts and marks pass/fail) · stop on
stalls.

**"Done" ladder**: agent says so < harness runs agent's tests < separate skeptical evaluator (read-only, structured
verdict, fails closed) < hidden acceptance tests. Metric: **overclaims** = believed passing − actually accepted.

**Hooks** (always run): pre-tool (block, reason to the model) · post-tool (feedback) · stop (refuse while red; cap
it). Mechanical rules → hooks; judgment → prompt.

**Knowledge**: AGENTS.md/CLAUDE.md = always on, short · skills = index in prompt, body on demand (measure loads).

**Ablation**: single → loop → loop+verify → full; per model; accepted, overclaims, tamper, $, turns, time.

`python -m agentlab.harness run --configs single,loop,loop+verify,full --models fast`
`python -m agentlab.harness new /tmp/promo-cc` · `python -m agentlab.harness accept /tmp/promo-cc`
