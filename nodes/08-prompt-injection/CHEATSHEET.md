# Node 08 cheat sheet: prompt injection

**Unsolved at the model level**: instructions and data share one channel. Model resistance is a probability.
**Lethal trifecta**: private data + untrusted content + external communication → exfiltration. Drop a leg.
**Rule of Two**: per session, at most two of {untrusted input, sensitive access, state change / external comms}.

**Attacks**: direct instruction · fake role markers · authority claims · fake tool results · obfuscation (base64,
other languages, Unicode tags) · exfil channels (markdown images, links, email, tool args) · conditional triggers ·
hidden text. Goals: exfiltrate, act, corrupt output, persist (memory, files).

**Lower the odds** (not boundaries): model training · spotlighting (random-tag delimiters) · detectors ·
output handling (no auto-rendered images/links). Filters fail to base rates + adaptive attackers + semantics.

**Measure**: ASR (security graders on attacked tasks) AND utility (attacked + benign look-alikes) · approvals/task ·
state-based graders · canary for prompt leaks · adaptive attacks, not just static sets.

**Architecture** (holds when the model is compromised): least privilege per task · allowlists from the TRUSTED
request · exfil checks on bodies · human approval for irreversible actions after taint · flow policy before every
call · plan-then-execute + quarantined model (no tools, no secrets) with per-value provenance.
Cost: no data-dependent control flow; quarantined text is still untrusted for humans.

`python -m agentlab.security detect-eval` · `attack --model fast --item db1201` ·
`run --suite nodes/08-prompt-injection/evals/ops --model fast --defenses none,spotlight,filter,taint,plan`
