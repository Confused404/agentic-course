# Node 10 cheat sheet: multi-agent systems

**Helps via**: more total context (workers read, lead gets compressed results) · parallel wall time · isolation
(worker mess and untrusted text stay in the worker). Not via "specialist personas".
**Costs**: tokens (every agent pays its own prompt; the lead re-reads reports) · lost context (worker sees only the
brief) · merge failures · coordination failures · seven transcripts instead of one.

**Use when**: breadth-heavy, independent pieces · read-mostly workers, one writer · single agent demonstrably fails
· answer is worth the token multiple. **Writes stay single-threaded.**

**Brief** = objective + definitions + scope + output shape (combinable fields: sums and counts) + effort.
**Enforce**: scoped tools, schema'd report tool (once), bounded fan-out, parallel execution, per-agent traces.

**Merge** (`reconcile`): missing shards listed · last report per shard wins · duplicates kept once · conflicts
withheld + surfaced · off-assignment reports ignored · never mutate inputs.

**Measure**: accuracy vs gold · tokens/task and × vs single · tokens by role · peak prompt · p50 wall time · agents ·
calls · missing shards · conflicts. Read failures per task.

**Alternatives first**: a fixed workflow (code splits, retries, one reducer) · a better tool (aggregate in the tool).

`python -m agentlab.multi run --archs single:fast,orch:fast:fast,mapreduce:fast:fast`
`python -m agentlab.multi show runs/multi/<ts> --task restock --arch orch:fast:fast --agent lead`
