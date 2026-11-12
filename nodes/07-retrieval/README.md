# Ticket KB-07: Answer from the knowledge base: RAG, agentic search, or long context?

| | |
|---|---|
| **Estimate** | 2.5 days |
| **Cost cap** | ≈ $1.50 (retrieval evals are free; QA runs ≈ $1; a vendor check ≈ $0.30) · Free models: $0 but ≈ 300–500 requests (retrieval evals are free) |
| **Prerequisites** | Node 04 (evals, stats), Node 06 (context budget). the `retrieval` extra (installed by `make setup`) for real embeddings |
| **You will touch** | `chunk.py`, `metrics.py`, `evals/mine/mine.yaml` (yours); index, QA modes, evals, CLI (agent); `docs/adr/0005-*` |
| **Done when** | `make grade N=07` green · retrieval table by type at 3 chunk sizes (150/400/1200) · QA comparison of 4 modes with the 2×2 diagnosis · 10 own questions · ADR 0005 |

## Story
Customers and staff ask questions the database can't answer: warranty terms, care instructions, error codes, which
products have a 5-year frame warranty. The answers are in ~220 knowledge-base documents, including archived pages that look
almost identical to current ones but have stale numbers. You'll build the retrieval stack (chunking, BM25, vectors,
hybrid fusion) and measure it without spending a cent. Then you'll compare three ways of answering: a RAG pipeline,
an agent with search tools, and the whole KB in a cached prompt. You'll decide with numbers, by question type, and
learn to tell retrieval failures from generation failures.

## Deliverables
1. `agentlab/retrieval/chunk.py::chunk_markdown`: **by hand** (AGENT-OFF).
2. `agentlab/retrieval/metrics.py` (hit@k, recall@k, MRR, nDCG@k, RRF): **by hand** (AGENT-OFF).
3. Index (FTS5 + sqlite-vec), embedders, QA modes, retrieval and QA evals, CLI: coding agent, from `SPEC.md`.
4. `nodes/07-retrieval/evals/mine/mine.yaml`: ten labelled questions, two of them adversarial to your best retriever.
5. `docs/adr/0005-knowledge-retrieval.md`.

## Time boxes
| Step | Box | Escape hatch |
|---|---|---|
| TEXTBOOK + predictions | 2.5h | |
| `chunk_markdown` | 1.5h | `git show solution/node-07:agentlab/retrieval/chunk.py`; then rewrite |
| metrics + RRF | 1h | same, `metrics.py` |
| Agent builds SPEC + review | 1.5h | `make solution N=07` |
| Retrieval experiments | 2h | skip the header ablation |
| Own questions | 1h | six instead of ten |
| QA runs + 2×2 | 2h | two modes instead of four |
| Vendor check + ADR | 1h | |

## Rubric (0–2 each)
| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Chunking | tests fail | tests pass | + chunk-size and header experiments explained by mechanism |
| Retrieval measurement | averages | by type | by type, misses read, labels checked |
| Architecture comparison | one mode | four modes, accuracy | accuracy by type, $/q, latency, paired CI |
| Diagnosis | "it got it wrong" | some failures read | every failure classified retrieval vs generation |
| Own questions | none | ten | ten incl. two that beat your best retriever, with why |
| Decision | preference | numbers | numbers + the triggers (scale, permissions) that would change it |
