# Node 09 cheat sheet: workflows

**Spectrum**: code → one call → workflow (fixed graph) → agent (model picks steps) → multi-agent. Go right only when
steps can't be known in advance. Start with a rules baseline.

**Patterns**: chaining (A→B→C) · routing (classify → handler) · parallel sectioning / voting · orchestrator-workers
(Node 10) · evaluator-optimizer (rubric, structured verdict, bounded rounds, fail closed). All plain code.

**Structured outputs**: enums for anything code branches on; schema-constrained; still validate; unparseable =
error, never a default. Untrusted text in → one enum out: small blast radius.

**Confidence**: sample agreement (n parallel calls) or logprobs; not self-reported numbers.
**Selective prediction**: coverage–accuracy curve; lowest threshold meeting the target; humans take the rest;
check the threshold on held-out.

**Cascade**: rules → cheap × n votes (accept if agreement ≥ t) → strong → human. Measure stage counts, $/item.

**Classifier evals**: macro-F1 + confusion matrix + easy/hard slices + acceptable alternatives + coverage + $ + p95.

`python -m agentlab.workflows triage --methods rules,llm:fast,vote:fast:5,cascade:fast:5:0.8:mid,agent:fast`
`python -m agentlab.workflows report runs/workflows/<ts> --a llm:mid --b cascade:fast:5:0.8:mid`
