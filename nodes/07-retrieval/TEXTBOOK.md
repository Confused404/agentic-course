# Node 07 Textbook: Retrieval: RAG, agentic search, and long context

> Prerequisites: Node 01 (§3 caching, §7 long context), Node 02 (tools, the loop), Node 04 (evals, paired
> comparisons), Node 06 (the context budget). Dated details (embedding models, provider features, sqlite-vec
> install notes) are in `APPENDIX-2026-11.md`.

## Learning objectives
1. Decide when a model needs retrieval at all, versus putting the knowledge in the prompt.
2. Build the retrieval pipeline end to end: chunking, lexical (BM25) and dense (embedding) indexes, hybrid fusion,
   reranking, prompt assembly with citations.
3. Explain *why* BM25 wins on some questions and embeddings on others, from how each works.
4. Measure retrieval on its own (hit@k, recall@k, MRR, nDCG) before measuring answers.
5. Compare three architectures (pipeline RAG, agentic search, long context) on accuracy, cost and latency, by
   question type, and say which failure belongs to retrieval and which to generation.
6. Handle what breaks real systems: stale near-duplicates, unanswerable questions, permissions, freshness, and
   retrieved text that is untrusted.

---

## §1 Why retrieval, and when not to

A model knows what was in its training data, up to its cutoff, and nothing about your company. To answer "what's the
warranty on the 65 W charger?" it needs your documents at inference time. There are three ways to get them there:

| Approach | How | Good when | Bad when |
|---|---|---|---|
| **Long context** | put the whole knowledge base in the prompt (cached) | the corpus fits comfortably (windows are 200K–1M tokens in 2026, but quality and cost argue for far less), changes rarely, everyone may see all of it | it doesn't fit; it changes per user or per minute; cost per query matters at volume; attention degrades (Node 06 §1) |
| **Pipeline RAG** | retrieve top-k chunks with a fixed procedure, put them in the prompt, one model call | large corpora; predictable cost and latency; questions answered by one or two passages | questions needing many documents (aggregation); retrieval misses are unrecoverable |
| **Agentic search** | give the model search/grep/read tools in a loop | the model needs to explore, refine queries, read whole documents, find *all* matches | latency and cost are several calls; the model must know how to search |

(Fine-tuning a model on your documents is rarely the right tool for *knowledge*: it's expensive to update,
can't cite, and still hallucinates. It's for behaviour and format. Elective E2 compares it to harness changes.)

Shopfront's knowledge base (`data/kb`, ~220 documents, ~24K tokens; ~15K for the ~100 current ones that long
context sends) is deliberately small enough that long context is a real contender. That's the honest 2026 situation for many internal knowledge bases. This node measures all
three, so your conclusion comes from data, not fashion.

---

## §2 The pipeline

```
 OFFLINE (when documents change)                ONLINE (per question)
 documents ─▶ chunk ─▶ ┬─▶ BM25 index (FTS5)     question ─▶ ┬─▶ BM25 top-N ─┐
                       └─▶ embed ─▶ vector index             └─▶ dense top-N ─┴▶ fuse (RRF) ─▶ [rerank] ─▶ top-k
                                                                                                  │
                                         answer + citations ◀── model ◀── prompt: rules + <documents> + question
```

Everything here lives in one SQLite file: a `docs` table, a `chunks` table, an FTS5 virtual table for BM25, and a
sqlite-vec `vec0` table for vectors. Production systems use a search engine or a vector database for scale, but the
moving parts are the same, and here you can read every one of them.

Metadata travels with each chunk: document id (for citations), title, **status** (current / archived /
discontinued) and date. Filters on metadata (exclude archived; only what this user may see) happen **in the
retriever**, before anything reaches the model.

---

## §3 Chunking

You don't index whole documents: long documents dilute a match (one relevant paragraph in five pages), and you
can't afford to put many whole documents in the prompt. You index **chunks**.

**Size.** Small chunks (100–300 tokens) match precisely but lose context ("Hand-wash only." — which product?).
Large chunks (1,000+ tokens) carry context but dilute the match and cost prompt space. A few hundred tokens is a
common starting point; the right size is an experiment (YOU_DO task 5).

**Follow the structure.** Split at headings, then paragraphs, then sentences, and only as a last resort mid-text.
A chunk should be a unit of meaning: one section, one FAQ answer, one spec list.

**Overlap.** When a section is split, repeating the tail of one piece at the start of the next keeps a fact that
straddles the boundary whole in at least one chunk. It costs index size and duplicate hits.

**Contextual headers.** Prefix every chunk with where it came from: `[Trailhead Tent (3-person)] Trailhead Tent
(3-person) > Care` (title, then heading path; redundant when the H1 repeats the title, and harmless). This is the
cheap version of what Anthropic calls *contextual retrieval*: there, a model writes a sentence of context for each
chunk before indexing, which cut retrieval failures substantially in their tests (more with BM25 + reranking).
Headings give most of the benefit at zero cost when documents are well structured; the LLM-written version helps
when they aren't.

**Other patterns you'll meet:** parent-document retrieval (match small chunks, return their larger parent);
per-type chunking (code by function, tables by row); keeping tables and lists intact.

You write `chunk_markdown` by hand (YOU_DO task 2): heading paths, contextual header, size limit with paragraph →
sentence → hard splits, overlap, full coverage.

---

## §4 Lexical and dense retrieval

### BM25 (lexical)
BM25 scores a chunk by the query terms it contains: each term contributes more if it's **rare** in the corpus
(inverse document frequency), with diminishing returns for repeats (term-frequency saturation, parameter k1), and
less in long chunks (length normalisation, parameter b). It has no idea what words *mean*.

- **Strong** at exact identifiers (`ELE-0048`, error codes like `E2`), rare product names, numbers, jargon. Exactly
  the things embeddings blur.
- **Weak** at paraphrase: "my head torch keeps switching on in my rucksack" shares no content word with
  "headlamp lockout mode".
- **The tokenizer matters.** FTS5's `porter unicode61` lowercases, splits on punctuation (`ELE-0048` → `ele`, `0048`,
  matched as a phrase when quoted) and stems (`flickers` → `flicker`).
- **Query construction matters.** Raw user text breaks FTS5 syntax (`"`, `-`, `AND`, `NEAR(`), so every token is
  quoted. Terms are OR-ed (AND returns nothing if one word is missing). And with OR, stopwords must go: otherwise
  "what's the capacity of KIT-0011" ranks short FAQ chunks full of "what" and "the" above the page with the SKU.
  (You'll see this happen in the tests: it's a real bug the reference implementation had.)

### Dense (embeddings)
An embedding model maps text to a vector (a few hundred to a few thousand numbers) such that texts with similar
meaning land near each other. Retrieval = embed the query, return the chunks with the highest cosine similarity.

- **Strong** at paraphrase and vocabulary mismatch: "blink and hum" ≈ "flicker".
- **Weak** at exact tokens and numbers (`ELE-0047` vs `ELE-0048` embed almost identically), negation ("not
  waterproof" ≈ "waterproof"), and very short queries.
- **Query/document asymmetry.** Many models expect queries and documents to be embedded differently (BGE models
  add an instruction prefix to queries). Using the document path for queries quietly costs accuracy.
- **Choose by evaluating on your data.** Public leaderboards (MTEB) are a starting list, not an answer. A small
  local model (bge-small, 384 dimensions) is often within a few points of large hosted ones on a narrow domain.
- **Search cost.** sqlite-vec's `vec0` does exact (brute-force) nearest-neighbour search: fine to hundreds of
  thousands of vectors. Beyond that, approximate indexes (HNSW, IVF) trade a little recall for speed.
- **Filtered search: pre-filter, don't post-filter.** "The 10 nearest current chunks" is not "the 10 nearest chunks,
  minus the archived ones". Here about half the chunks are archived near-duplicates, so post-filtering a top-30
  often leaves 11. Put the filter *inside* the KNN query (the index stores `status` as a metadata column), or, in
  engines that can't, over-fetch and loop until you have k. Approximate indexes make this harder still: a
  restrictive filter can starve an HNSW search; check what your engine does.
- **Model-specific prefixes.** Several embedding models were trained with prefixes on queries and documents
  (e5: `query:`/`passage:`; nomic: `search_query:`/`search_document:`; bge: an optional query instruction).
  Leaving them out costs accuracy silently. The embedder keeps an explicit table; check the model card.
- **Re-embed on model change.** Vectors from different models are incompatible; the index cache key includes the
  embedder name.

The test suite uses a **hash embedder** (character n-grams, no model) so everything runs offline. It captures
spelling overlap, not meaning. It tests plumbing; never judge dense retrieval by it.

---

## §5 Hybrid search and reranking

BM25 and dense retrieval fail on different questions, so combine them. Their scores aren't comparable (BM25 is
unbounded, cosine is in [−1, 1], and both shift with the query), so fuse **ranks**, not scores. Reciprocal Rank
Fusion:

```
RRF(d) = Σ over rankings r containing d of  1 / (k + rank_r(d))        (k = 60 by convention)
```

A document ranked high by either retriever rises; one ranked moderately by both rises further. RRF has one
parameter, needs no training, and is hard to beat as a default. You write it (with the metrics) in YOU_DO task 3.

**Reranking.** Retrievers compare a query vector with a chunk vector computed separately (a *bi-encoder*). A
**cross-encoder** reads the query and the chunk *together* and outputs a relevance score: much more accurate, far
too slow to run over the whole corpus. So: retrieve 30–100 candidates cheaply, rerank them, keep the top 5. An LLM
can also act as the reranker (or simply as the reader of 20 candidates). Rerankers are the usual next step when
recall@50 is high but precision@5 is not (stretch task).

---

## §6 Measuring retrieval

Measure retrieval **before** answers: it's free (no model calls), instant, and tells you whether the answer can
possibly be right. You need a labelled set: questions with their **gold** documents.

| Metric | Question it answers |
|---|---|
| **hit@k** | Is at least one gold document in the top k? (Can a one-document question be answered?) |
| **recall@k** | What fraction of the gold documents are in the top k? (Multi-hop and aggregation need all of them.) |
| **MRR** | How high is the first gold document? (1, ½, ⅓, …) |
| **nDCG@k** | Are the gold documents near the top, with position discounted logarithmically? |

Work at the **document** level (dedupe chunks by document) when gold labels are documents. Report by **question
type**: an average hides that BM25 aces identifiers and fails paraphrases.

Pitfalls:
- **Incomplete gold labels.** If another document also answers the question, a retriever that finds it is scored
  as a miss. When you read misses, check the label first.
- **Near-duplicates.** The archived 2024/2025 product pages are near-copies of current pages with stale numbers. With
  archived documents included, a retriever can fill the top 5 with versions of the same product.
- **Unanswerable questions** have no gold; they're excluded from retrieval metrics and tested end to end
  (does the model say "not in the knowledge base"?).

---

## §7 Pipeline RAG vs agentic search vs long context

You'll run the same 30 questions through four configurations: `rag:bm25:5`, `rag:hybrid:5`, `agentic` (tools:
`search_kb`, `grep_kb`, `read_doc`) and `longctx` (the current KB in a cached system prompt). What to expect, and
why:

- **Aggregation** ("which products have a 5-year frame warranty?") needs *every* matching document: nine product
  pages across four product families. RAG with k=5 can't see nine matches; agentic search can `grep_kb('IP65')`; long context has everything.
- **Paraphrase** favours dense/hybrid retrieval and long context; agentic search depends on the model
  reformulating its query (models are decent at this: it's what they do in Claude Code with grep).
- **Identifiers** are easy for BM25, grep and long context; pure dense retrieval may miss.
- **Stale traps**: long context with archived documents included, or RAG that doesn't filter, can answer from the
  2024 page. The 2024 pages say "ARCHIVED" in their text; the 2025 pages look exactly like current ones and only
  their metadata says otherwise, which is how most real archives look. Filtering is cheap; the status attribute
  in the prompt is a second line. Measure what each buys with `rag+archived:...` and `longctx+archived`.
- **Cost and latency**: RAG is one call with a few thousand tokens. Long context is one call with the whole KB,
  mostly cache reads after the first. Agentic is several calls whose context grows.

This is the same trade-off coding agents face. Claude Code and OpenCode search code with grep, glob and file reads
instead of a vector index; Claude Code's developers have said publicly that agentic search beat their early
embedding-based retrieval for code. Code is full of exact identifiers, changes constantly (indexes go stale), and
rewards reading whole files. Your support KB is different, which is why you measure instead of copying.

### Diagnosing a wrong answer: the 2×2
Every failed QA trial is one of four things. The runner records what the model was **shown** (`shown_recall`), so
you can classify:

| | answer right | answer wrong |
|---|---|---|
| **gold shown** | fine | **generation failure**: the model had it and didn't use it (prompt, distraction, wrong doc preferred) |
| **gold not shown** | lucky, or the question is answerable from elsewhere (check the label) | **retrieval failure**: fix retrieval, not the prompt |

Fixing a retrieval failure with prompt changes is the most common wasted effort in RAG projects.

---

## §8 Answer quality and production concerns

- **Grounding rules.** Answer only from the documents; cite each fact with a document id; prefer current over
  archived; and if the documents don't answer it, say so, using a fixed phrase so it can be graded. A model that
  falls back to general knowledge on an unanswerable question is the most damaging failure: confident and wrong.
- **Citations** let users and graders check. Check them mechanically: do the cited ids exist, and are they gold?
  The runner reports "cites gold" per mode.
- **Faithfulness.** An answer can cite the right document and still say something the document doesn't. An LLM
  judge comparing claims with the cited text catches this (Node 04's judge, calibrated); frameworks such as RAGAS
  package metrics like faithfulness and context precision/recall.
- **Freshness.** The index is a copy. Rebuild when documents change (the cache key covers the corpus, the
  chunker's code and settings, and the embedder), and show `updated` dates. At scale you re-index
  incrementally: hash each document, re-chunk and re-embed only those whose hash changed, delete the chunks of
  removed documents. Agentic search over live sources avoids staleness at the cost of speed.
- **Permissions.** If some documents are internal, filter in the retriever by the user's access. Never put a
  document in the prompt and tell the model not to reveal it.
- **Retrieved text is untrusted input.** A document, a review or a web page can contain instructions. The answer
  rules say documents are reference material, and tags are escaped, but that is mitigation, not a defence. Node 08
  is about the defence.

### Beyond this node
Query rewriting (expand or decompose the question before retrieving; HyDE embeds a hypothetical answer instead of
the question), multi-query retrieval, late-interaction models (ColBERT), graph-based retrieval for questions about
relationships, and fine-tuned embedding models for very specialised vocabularies. Each is an experiment worth
running only after your basic pipeline is measured.

---

## Design trade-offs

| Decision | Options | Guidance |
|---|---|---|
| Architecture | long context / RAG / agentic / hybrids | small stable corpus: try long context first; large: RAG; exploratory or "find all": agentic |
| Retriever | BM25 / dense / hybrid | hybrid (RRF) by default; BM25 alone is a strong baseline, so measure before adding vectors |
| Chunk size | small / medium / large | structure-aware, a few hundred tokens, contextual headers; tune on retrieval metrics |
| k | 3 / 5 / 10+ | enough for recall@k on multi-hop; more k costs tokens and distracts |
| Reranker | none / cross-encoder / LLM | add when recall@50 ≫ precision@5 |
| Stale content | filter / label / both | filter in the retriever and label in the prompt |
| Unanswerable | answer anyway / abstain | abstain with a fixed phrase; test it |

## Common failure modes and debugging

| Symptom | Likely cause | Fix |
|---|---|---|
| sqlite3.OperationalError: fts5 syntax error | raw user text in MATCH | quote every token (`fts_query`) |
| SKU questions rank FAQ chunks first | stopwords OR-ed into the query | drop stopwords; BM25 then favours rare terms |
| Right product, wrong number (2.83 kg) | archived near-duplicate retrieved | filter `status != 'archived'`; status in the prompt |
| "Which products..." misses half | top-k too small for aggregation | agentic grep, or long context, for list questions |
| Paraphrased questions miss | BM25 only | hybrid with a real embedding model |
| Dense search misses exact codes | embeddings blur identifiers | hybrid; BM25 carries identifiers |
| Confident answer to an unanswerable question | no abstention rule, or the model ignored it | fixed abstain phrase; test unanswerables |
| Wrong answer although the gold doc was shown | generation failure | read the prompt; reduce k or distractors; clarify rules |
| Scores look great, users unhappy | gold labels incomplete or questions unrepresentative | read misses; add real questions (flywheel) |
| Dense results change after an upgrade | new embedding model, old vectors | rebuild: the cache key includes the embedder |

## Self-check
1. Name two question types where BM25 beats dense retrieval, and two where dense wins. Explain from the mechanisms.
2. Why fuse ranks instead of scores?
3. Your retriever's recall@5 on multi-hop questions is 0.5 and hit@5 is 1.0. What does that mean for answers?
4. A QA trial failed and `shown_recall` is 1.0. Is it a retrieval or a generation failure? What do you read next?
5. The KB is 27K tokens. Give two reasons long context might still be the wrong choice for a production assistant.
6. Why must permission filtering happen in the retriever rather than in the prompt?
7. Why does the reference `fts_query` drop stopwords, and what would happen if it AND-ed the terms instead?
8. What does the contextual header buy for BM25, and what does it buy for the model reading the chunk?

<details><summary>Answers</summary>

1. BM25: exact identifiers (SKUs, error codes) and rare terms or numbers, because it matches tokens exactly and
   weights rare ones. Dense: paraphrases and vocabulary mismatch ("blink and hum" vs "flicker"), because similar
   meanings embed near each other regardless of words.
2. BM25 and cosine scores live on different, query-dependent scales; adding them lets one dominate arbitrarily.
   Ranks are comparable.
3. Every question has *some* gold document in the top 5, but on average only half of what's needed: multi-hop
   answers will be incomplete or wrong even when the single-hit view looks perfect.
4. Generation: the model saw every gold document. Read the prompt it got (which other documents were there, any
   archived ones, how long it was) and the answer against the gold text.
5. Any of: it will grow past the point where it fits or stays cheap; per-user permissions mean different users
   must see different content; freshness (a cached prompt must be rebuilt on every change); attention degrades
   with length; cost per query at high volume.
6. Anything in the prompt can come out (prompt injection, or plain model error). Only data the user may see should
   reach the model.
7. With OR, stopwords match nearly every chunk, so short chunks dense in "what/the/of" outrank the one that has the
   rare, decisive term. AND would return nothing whenever any single word is absent from a chunk.
8. For BM25: the product name and section words become matchable terms in every chunk of that page. For the model:
   it knows which product and which section a fragment like "Hand-wash only." refers to.
</details>

## Socratic review prompt
> Read nodes/07-retrieval/TEXTBOOK.md, my agentlab/retrieval/chunk.py and metrics.py, my retrieval results in
> runs/ and docs/adr/0005-knowledge-retrieval.md. Don't write code. Ask me 6 questions, one at a time, that test
> whether my choice of architecture would survive the knowledge base growing 100×, and per-user permissions being
> added. Push on anything I justified only with averages.
