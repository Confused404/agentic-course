# Ticket ARCH-16: "Should we be on a framework?"

| | |
|---|---|
| **Estimate** | 1 day |
| **Cost cap** | ≈ $0.10–0.30 for the comparison on paid `fast` (11 regression tasks × 3 implementations); the approval drill is a few calls. Tasks 2, 3 and 5 are free. Free models: $0 but ≈ 150 requests for the comparison plus judge calls, over the 50-a-day allowance: run one implementation a day (`--impls`), or use the 1,000/day tier |
| **Prerequisites** | Node 02 (your loop), Node 04 (evals), Node 05 (prompt/tool variants), Node 14 (durable runs and approvals) |
| **You will touch** | `agentlab/frameworks/{convert.py,graph_nodes.py}` (yours); the two ports, the comparison, the CLI and a small hook in `agentlab/evals/runner.py` (agent); `docs/adr/0013-*` |
| **Done when** | `make grade N=16` green · the same graders scored all three implementations · a crash/approval drill on LangGraph compared with Node 14 · ADR 0013 |

## Story
A new hire asks why Shopfront runs "a homemade agent loop" when Pydantic AI and LangGraph exist. Fair question.
You've built every piece by hand on purpose; now you know what each piece is for, so you can judge what a
framework gives you, what it hides, and what it costs to leave. Port the support assistant to both, score all three
with the same graders, put the two frameworks' persistence next to your Node 14 journal, and write the decision.

## Deliverables
1. `convert.py::to_course_messages` and `graph_nodes.py::tools_node`: **by hand** (AGENT-OFF). The first is the
   seam that makes a framework measurable with your own evals; the second is where LangGraph's resume semantics
   bite.
2. The Pydantic AI port, the LangGraph port, the comparison harness and CLI, and the runner hook: coding agent,
   from `SPEC.md`.
3. The comparison table: pass rate, cost, calls, tokens, latency, code size.
4. A LangGraph approval that survives a process exit, and a crash drill compared with Node 14.
5. `docs/adr/0013-frameworks.md`.

## Time boxes
| Step | Box | Escape hatch |
|---|---|---|
| TEXTBOOK + predictions | 1h | |
| convert.py + graph_nodes.py | 1.5h | `git show solution/node-16:agentlab/frameworks/convert.py` |
| Agent builds SPEC + review | 1.5h | `make solution N=16` |
| Comparison run | 45m | `--impls native,langgraph` |
| Approval + crash drills | 1h | |
| ADR | 30m | |

## Rubric (0–2 each)
| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Measurement | "it works in the framework too" | same graders on all three | + differences explained from transcripts (tokens, calls, error handling), noise acknowledged |
| Persistence | not compared | features listed | + crash and approval drills run; where each design can repeat a side effect, and what prevents it |
| Costs of adoption | none named | some | + upgrade churn, debugging depth, hidden prompts/retries, lock-in, and the exit plan |
| Decision | "frameworks are bad/good" | a choice | a choice per component (loop, tools, persistence, observability), with what would change your mind |
