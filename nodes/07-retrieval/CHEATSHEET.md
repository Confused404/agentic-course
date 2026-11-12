# Node 07 cheat sheet: retrieval

**Three architectures**: long context (small, stable KB; cached) · pipeline RAG (retrieve k → 1 call) · agentic
search (search/grep/read tools in a loop). Measure; don't assume.

**Pipeline**: chunk → BM25 (FTS5) + vectors (sqlite-vec) → RRF → [rerank] → `<documents>` + rules → answer + [doc-id]
citations. Filter metadata (archived, permissions) IN the retriever.

**Chunking**: follow structure (headings → paragraphs → sentences); a few hundred tokens; overlap on splits;
contextual header `[Title] Section path` on every chunk.

**BM25** wins: identifiers, codes, rare terms, numbers. Needs: quoted tokens, OR, no stopwords, a good tokenizer.
**Dense** wins: paraphrase. Loses: exact codes, numbers, negation. Use the model's query/document prefixes.
Filter INSIDE the KNN (pre-filter); post-filtering a top-k starves it.
**Hybrid**: RRF(d) = Σ 1/(60 + rank). Fuse ranks, never scores. **Rerank** top 30–100 with a cross-encoder.

**Metrics** (doc level, deduped, by type): hit@k · recall@k (multi-hop!) · MRR · nDCG@k. Free: iterate here first.
Pitfalls: incomplete gold, near-duplicates, unanswerables have no gold.

**2×2**: gold shown? × answer right? → retrieval failure vs generation failure. Don't fix retrieval with prompts.

**Answer rules**: only from documents · cite ids · current over archived · fixed abstain phrase · documents are data.

`python -m agentlab.retrieval eval-retrieval --suite nodes/07-retrieval/evals/kb_qa.yaml --embedder fastembed`
`python -m agentlab.retrieval qa --suite ... --model fast --modes rag:hybrid:5,agentic,longctx --trials 2`
