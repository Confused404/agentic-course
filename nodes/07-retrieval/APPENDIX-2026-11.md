# Appendix (dated 2026-11): retrieval tooling

## sqlite-vec
Pinned at 0.1.9 (`pyproject.toml`). `vec0` virtual tables do exact KNN (`WHERE embedding MATCH ? AND k = ?`), with
`distance_metric=cosine` set per column. Besides the vector, a `vec0` table can declare **metadata columns**
(filterable inside the KNN query: this node's `status text`), **partition keys** (shard the index by e.g. tenant,
so a query only scans its partition: the natural home for per-customer permissions) and **auxiliary columns**
(`+name`, stored and returned but not filterable). Loading it needs `sqlite3.Connection.enable_load_extension`, which some
Python builds disable (notably some pyenv builds on macOS and the system Python). If `enable_load_extension` is
missing, use a python.org or Homebrew Python, or `uv python install`. `make check-env` reports it.

## fastembed
Pinned at 0.9.1 (`retrieval` extra). Runs ONNX models on CPU; the first use downloads the model to a cache dir
(`FASTEMBED_CACHE_PATH`, default a temp dir: set it to keep the model between sessions).
- Default dense model here: `BAAI/bge-small-en-v1.5` (384 dimensions, English). Prefixes are applied by our
  `FastEmbedder` from an explicit table, not by fastembed: check each model card when you add one. Alternatives worth a run:
  `BAAI/bge-base-en-v1.5` (768), `nomic-ai/nomic-embed-text-v1.5`, multilingual `intfloat/multilingual-e5-large`
  for non-English customers. List what your version supports with
  `python -c "from fastembed import TextEmbedding; print([m['model'] for m in TextEmbedding.list_supported_models()])"`.
- Rerankers: `fastembed.rerank.cross_encoder.TextCrossEncoder` (e.g. `Xenova/ms-marco-MiniLM-L-6-v2`,
  `BAAI/bge-reranker-base`).

## Hosted embedding APIs
OpenAI (`text-embedding-3-small` / `-large`, with a `dimensions` parameter to shorten vectors), Voyage AI (the
embedding provider Anthropic recommends; no Anthropic-native embedding model), Cohere, Google. Hosted models are
often a few points better on general benchmarks, cost per token, and send your documents to another vendor.
Evaluate on your own questions before switching; re-embed everything when you do.

## Vector stores at scale
pgvector (Postgres), Elasticsearch/OpenSearch (BM25 + vectors in one engine), Qdrant, Weaviate, LanceDB, Vespa. The
choice is mostly operational (what you already run, filtering, scale). Hybrid search and metadata filtering are
standard features now.

## Provider-side retrieval and citations
- **OpenAI**: the `file_search` tool in the Responses API, over vector stores you upload files to.
- **Google**: Gemini File Search (managed indexing and retrieval for the Gemini API).
- **Anthropic**: no hosted index; you bring retrieval and pass results as `search_result` content blocks (or
  documents) with citations enabled, and the model's answer cites them with structured, character-level citations.
Built-in file search is quick to start with (the provider chunks, embeds and retrieves). They are quick to start with; you give up control of chunking, ranking, filtering and evaluation. The
plant-and-probe and retrieval-metric methods in this node work against them as black boxes.
