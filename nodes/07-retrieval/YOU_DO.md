# Node 07: your work

Cost note: retrieval evals are free (no model calls). End-to-end QA is cheap on `fast`: 30 questions × 4 modes ×
2 trials is roughly 3M input tokens, most of it cache reads for `longctx`: well under $1. Real embeddings need
`make setup` installed the `retrieval` extra (if it failed then: `uv pip install --python .venv -e '.[retrieval]'`); the first use downloads a ~100 MB model.

### 1. [PREDICT] Before anything runs (20 min)
Read `evals/kb_qa.yaml`. In `LEARNING_LOG.md`, for each question **type**, predict which retriever wins hit@5
(BM25, dense, hybrid), and which architecture wins accuracy (`rag:hybrid:5`, `agentic`, `longctx`). Then rank the
three architectures by $/question and by latency. One sentence of reasoning per prediction, from TEXTBOOK §4 and §7.

### 2. [AGENT-OFF] `chunk_markdown` (≤ 1.5h)
`agentlab/retrieval/chunk.py`. Contract in the docstring; grader `tests/test_chunk.py`. Before coding, take
`data/kb/help-refund-policy.md` and `data/kb/product-OUT-0015.md` and write out by hand the chunks your function
should produce (headings, header lines). The coverage test runs over the whole KB.

### 3. [AGENT-OFF] Metrics and RRF (≤ 1h)
`agentlab/retrieval/metrics.py`; grader `tests/test_metrics.py`. Work out every expected value in the tests on
paper before running them, including the nDCG ones. For RRF, fuse `[a, b, c]` and `[c, a, d]` by hand.

### 4. Delegate, then review (≤ 1.5h)
`make new-ticket N=07` → coding agent: *"Implement nodes/07-retrieval/SPEC.md. Follow AGENTS.md. chunk.py and
metrics.py are mine; don't write them."*
Review for:
- **`fts_query`**: try `python -m agentlab.retrieval search 'ELE-0048 "not" AND NEAR(' --embedder none`. No crash?
- **Archived filtering in dense search**: does it over-fetch before filtering, or can it return fewer than k?
- **Tool descriptions** for `search_kb`/`grep_kb`/`read_doc`: would *you* know when to use which? Lint them with
  your Node 05 linter:
  `python -c "from agentlab.retrieval.qa import kb_tools; from agentlab.retrieval.index import KBIndex; from agentlab.tools.lint import lint_tools; print(lint_tools(kb_tools(KBIndex(), []).specs()))"`
- **Cache key**: change `--max-chars` and check that the index rebuilds; change nothing and check it doesn't.

### 5. Retrieval experiments: free (≤ 2h)
```bash
uv pip install --python .venv -e '.[retrieval]'      # only if make setup's retrieval step failed
.venv/bin/python -m agentlab.retrieval index --embedder fastembed
.venv/bin/python -m agentlab.retrieval eval-retrieval --suite nodes/07-retrieval/evals/kb_qa.yaml \
   --embedder fastembed --modes bm25,dense,hybrid -k 5
```
- **[LOG]** The table by type. Which of your task-1 predictions were wrong?
- **[READ-TRACE] Three misses.** For each question listed under "Missed entirely", run `search` with the question
  and each mode. What ranked instead, and why (from the mechanism)? Is the gold label complete?
- **Chunk size.** Re-run with `--max-chars 400` and `--max-chars 150 --overlap 0` (each builds its own index; most
  KB sections are a few hundred characters, so 1200 is "one chunk per section" and 150 splits nearly everything).
  Tabulate hit@5 and recall@5 by type against chunk size. Which types suffer from small chunks, and why? Do the
  contextual headers soften it?
- **Contextual header ablation.** Temporarily make your chunker skip the header line and re-run (the index cache
  key includes your chunker's code, so it rebuilds by itself). What changed, for which types? Then restore it.
- **`--archived`**: run once including archived documents. Which question types get worse, and how? Look at
  `tent3_weight`: what does the top 5 contain?

### 6. [AGENT-OFF] Ten questions of your own (≤ 1h)
Write `nodes/07-retrieval/evals/mine/mine.yaml` (its own folder, so it isn't mixed into the main suite): ten
questions in the same format, at least one per type, including
**two designed to defeat your best retriever** (look at its misses for ideas: vocabulary it can't bridge, a number
that appears in several near-duplicates). Label gold documents by searching the KB yourself (`grep -ril`).
`tests/test_kb_and_suite.py` checks the main suite's labels against the KB; run
`python -c "from agentlab.retrieval.qa_eval import load_qa; load_qa('nodes/07-retrieval/evals/mine')"` for yours, and
grep each gold document for your answer pattern.

### 7. End-to-end QA (≤ 2h, ≤ $1)
```bash
.venv/bin/python -m agentlab.retrieval qa --suite nodes/07-retrieval/evals/kb_qa.yaml --model fast \
   --embedder fastembed --modes rag:bm25:5,rag:hybrid:5,agentic,longctx --trials 2 --budget 1
.venv/bin/python -m agentlab.retrieval report runs/retrieval/<ts> --a rag:hybrid:5 --b agentic
```
- **The 2×2.** For every failed trial, use `extra.shown_recall` (was the gold shown?) to classify it as a retrieval
  or a generation failure (TEXTBOOK §7). Count them per mode. Which mode's failures are mostly retrieval?
- **Read** two generation failures in full: what was the model shown, and why did it answer wrongly?
- **Unanswerables**: which modes abstain? If one doesn't, is it the rules or the retrieved context that misled it?
- **Agentic traces**: which tools did it use for aggregation questions (`tool_calls` in each trial)? Did it ever
  grep? Did the ones that grepped get the 9-product question right?
- **What the filter buys**: one extra run with `--modes rag+archived:hybrid:5,rag:hybrid:5 --types stale`.
- Compare $/question and p50 latency with your task-1 ranking.
- Run your own questions separately (`--suite nodes/07-retrieval/evals/mine`).

### 8. One vendor check (≤ 30 min, ≤ $0.30)
Run your best two modes with `--model gpt-fast` (or `local`; if you opted into Ollama, its default context is 4K
tokens below 24 GB VRAM, which silently truncates `longctx` (~15K tokens) and long agentic transcripts: raise
`num_ctx` or leave those modes out). Does the ranking of architectures hold? Which
mode is most sensitive to the model?

### 9. [DECIDE] ADR 0005 (30 min)
`docs/adr/0005-knowledge-retrieval.md`: which architecture the support assistant should use for knowledge questions
today, with numbers (accuracy by type, $/q, latency). Then: what changes your answer if the KB grows 100×, or if
some documents become internal-only? State the trigger at which you'd switch.

### Stretch
- Add a cross-encoder reranker (`fastembed.rerank.cross_encoder.TextCrossEncoder`) over the hybrid top 30 and
  measure precision gains on retrieval metrics.
- Give the support assistant a `search_kb` tool backed by your index, replacing the help-center keyword search,
  and run the Node 04 suite to check for regressions.
