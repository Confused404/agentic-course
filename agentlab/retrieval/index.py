"""The knowledge-base index: SQLite holds documents, chunks, a BM25 index (FTS5) and a vector index (sqlite-vec)
(TEXTBOOK §4-§5). One file, no server: the same shape as a production RAG store, small enough to read.
"""
from __future__ import annotations

import json
import re
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path

import hashlib
import inspect

from agentlab.retrieval import chunk as chunk_module
from agentlab.retrieval.chunk import Chunk
from agentlab.retrieval.corpus import Doc, corpus_hash
from agentlab.retrieval.embed import Embedder
from agentlab.retrieval.metrics import dedupe, rrf_fuse

MODES = ("bm25", "dense", "hybrid")
# FTS5 query syntax treats these words as operators; quoting every token makes user text safe
_TOKEN = re.compile(r"[\w][\w.\-]*", re.UNICODE)


@dataclass
class Hit:
    chunk_id: str
    doc_id: str
    title: str
    status: str
    heading: str
    text: str
    score: float           # higher is better; only comparable within one mode


STOPWORDS = frozenset("""a an and are as at be but by can could did do does for from had has have how i if in into is it
its me my no not of on or our s should so than that the their them then there these they this to was we were what
when where which who why will with would you your""".split())


def fts_query(text: str) -> str:
    """User text -> a safe FTS5 query: content tokens double-quoted and OR-joined.
    why quoting: raw user text breaks FTS5 ('ELE-0048' parses as a column filter minus a term; a stray '"' is a
    syntax error) or turns into operators ('not', 'and', 'near').
    why OR: AND returns nothing for any question with one unmatched word; BM25 still ranks chunks matching more
    (and rarer) terms higher.
    why drop stopwords: with OR, "what's the ... of" matches every chunk, and short chunks full of "what"/"the"
    (FAQ lines) outrank the one with the SKU. If nothing is left, fall back to all tokens."""
    toks = [t.replace('"', "") for t in _TOKEN.findall(text)]
    content = [t for t in toks if t.lower() not in STOPWORDS and (len(t) > 1 or t.isdigit())]
    return " OR ".join(f'"{t}"' for t in (content or toks) if t) or '""'


def _blob(v: list[float]) -> bytes:
    return struct.pack(f"{len(v)}f", *v)


class KBIndex:
    def __init__(self, path: str | Path = ":memory:", embedder: Embedder | None = None) -> None:
        self.conn = sqlite3.connect(str(path))
        self.embedder = embedder
        self._vec = False
        if embedder is not None:
            import sqlite_vec
            self.conn.enable_load_extension(True)
            sqlite_vec.load(self.conn)
            self.conn.enable_load_extension(False)
            self._vec = True

    # ---- building
    def build(self, docs: list[Doc], *, max_chars: int = 1200, overlap_chars: int = 150) -> "KBIndex":
        key = self.build_key(docs, max_chars, overlap_chars)
        if self._meta("key") == key:
            return self                   # cached: same corpus, chunker settings and embedder
        c = self.conn
        try:
            c.execute("DROP TABLE IF EXISTS chunks_vec")
        except sqlite3.OperationalError:
            # a vec0 table can't even be dropped without the extension: this file was built with an embedder
            raise RuntimeError("this index file has vectors; open it with the same embedder, or use a new path")
        c.executescript("""
            DROP TABLE IF EXISTS docs; DROP TABLE IF EXISTS chunks; DROP TABLE IF EXISTS chunks_fts;
            DROP TABLE IF EXISTS meta;
            CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
            CREATE TABLE docs (id TEXT PRIMARY KEY, title TEXT, type TEXT, status TEXT, updated TEXT, text TEXT,
                               meta TEXT);
            CREATE TABLE chunks (rowid INTEGER PRIMARY KEY, id TEXT UNIQUE, doc_id TEXT, heading TEXT, text TEXT);
            -- porter: "flickers" matches "flicker"; unicode61 handles accents
            CREATE VIRTUAL TABLE chunks_fts USING fts5(text, content='chunks', content_rowid='rowid',
                                                       tokenize='porter unicode61');
        """)
        c.executemany("INSERT INTO docs VALUES (?,?,?,?,?,?,?)",
                      [(d.id, d.title, d.type, d.status, d.updated, d.text, json.dumps(dict(d.meta))) for d in docs])
        chunks: list[Chunk] = [ch for d in docs for ch in chunk_module.chunk_markdown(d, max_chars, overlap_chars)]
        c.executemany("INSERT INTO chunks (id, doc_id, heading, text) VALUES (?,?,?,?)",
                      [(ch.id, ch.doc_id, ch.heading, ch.text) for ch in chunks])
        c.execute("INSERT INTO chunks_fts (rowid, text) SELECT rowid, text FROM chunks")
        if self._vec:
            # why a metadata column: KNN with the filter INSIDE the query (pre-filtering). Filtering after a top-k
            # (post-filtering) returns fewer than k results when most neighbours are filtered out: here, half the
            # chunks are archived near-duplicates of the current ones (TEXTBOOK §4, filtered search).
            c.execute(f"CREATE VIRTUAL TABLE chunks_vec USING vec0(embedding float[{self.embedder.dim}] "
                      f"distance_metric=cosine, status text)")
            rows = c.execute("SELECT c.rowid, c.text, d.status FROM chunks c JOIN docs d ON d.id = c.doc_id "
                             "ORDER BY c.rowid").fetchall()
            for i in range(0, len(rows), 64):
                batch = rows[i:i + 64]
                vecs = self.embedder.embed([t for _, t, _ in batch], kind="document")
                c.executemany("INSERT INTO chunks_vec (rowid, embedding, status) VALUES (?, ?, ?)",
                              [(r, _blob(v), st) for (r, _, st), v in zip(batch, vecs)])
        c.execute("INSERT INTO meta VALUES ('key', ?)", (key,))
        c.commit()
        return self

    def build_key(self, docs, max_chars, overlap_chars) -> str:
        """Everything that changes the index: the corpus, chunker settings, the chunker module's CODE (so fixing
        your chunk_markdown rebuilds the index instead of silently reusing stale chunks), and the embedder."""
        emb = self.embedder.name if self.embedder else "none"
        try:
            code = hashlib.sha256(inspect.getsource(chunk_module).encode()).hexdigest()[:8]
        except (OSError, TypeError):
            code = "unknown"
        return f"{corpus_hash(docs)}:{max_chars}:{overlap_chars}:{code}:{emb}"

    def _meta(self, k: str) -> str | None:
        try:
            row = self.conn.execute("SELECT v FROM meta WHERE k = ?", (k,)).fetchone()
        except sqlite3.OperationalError:
            return None
        return row[0] if row else None

    # ---- searching
    def _hits(self, rows) -> list[Hit]:
        return [Hit(cid, did, title, status, heading, text, float(score))
                for cid, did, title, status, heading, text, score in rows]

    _SELECT = ("SELECT c.id, c.doc_id, d.title, d.status, c.heading, c.text, {score} FROM chunks c "
               "JOIN docs d ON d.id = c.doc_id ")

    def search_bm25(self, query: str, k: int = 10, include_archived: bool = False) -> list[Hit]:
        where = "" if include_archived else "AND d.status != 'archived' "
        sql = (self._SELECT.format(score="-bm25(chunks_fts)") +
               "JOIN chunks_fts ON chunks_fts.rowid = c.rowid WHERE chunks_fts MATCH ? " + where +
               "ORDER BY bm25(chunks_fts) LIMIT ?")
        return self._hits(self.conn.execute(sql, (fts_query(query), k)).fetchall())

    def search_dense(self, query: str, k: int = 10, include_archived: bool = False) -> list[Hit]:
        if not self._vec:
            raise RuntimeError("this index has no embedder: dense search unavailable")
        q = self.embedder.embed([query], kind="query")[0]
        where = "" if include_archived else " AND status != 'archived'"
        rows = self.conn.execute(
            f"SELECT rowid, distance FROM chunks_vec WHERE embedding MATCH ? AND k = ?{where} ORDER BY distance",
            (_blob(q), k)).fetchall()
        dist = {r: d for r, d in rows}
        if not dist:
            return []
        marks = ",".join("?" * len(dist))
        got = self.conn.execute(self._SELECT.format(score="c.rowid") + f"WHERE c.rowid IN ({marks})",
                                tuple(dist)).fetchall()
        hits = [Hit(cid, did, t, st, h, tx, 1 - dist[int(rid)]) for cid, did, t, st, h, tx, rid in got]
        return sorted(hits, key=lambda h: -h.score)[:k]

    def search(self, query: str, k: int = 10, mode: str = "hybrid", include_archived: bool = False,
               fetch: int = 30) -> list[Hit]:
        if mode == "bm25":
            return self.search_bm25(query, k, include_archived)
        if mode == "dense":
            return self.search_dense(query, k, include_archived)
        if mode == "hybrid":
            lists = [self.search_bm25(query, fetch, include_archived)]
            if self._vec:
                lists.append(self.search_dense(query, fetch, include_archived))
            by_id = {h.chunk_id: h for lst in lists for h in lst}
            fused = rrf_fuse([[h.chunk_id for h in lst] for lst in lists])[:k]
            return [Hit(**{**by_id[c].__dict__, "score": 1.0 / (i + 1)}) for i, c in enumerate(fused)]
        raise ValueError(f"unknown mode {mode!r}: {MODES}")

    def rank_docs(self, query: str, k: int = 10, mode: str = "hybrid", include_archived: bool = False) -> list[str]:
        """Document ids in rank order (first chunk wins), for retrieval metrics."""
        n = k * 3
        while True:      # why the loop: a document can own many chunks; widen until k distinct docs (or exhausted)
            hits = self.search(query, n, mode, include_archived, fetch=max(30, n))
            docs = dedupe([h.doc_id for h in hits])
            if len(docs) >= k or len(hits) < n:
                return docs[:k]
            n *= 2

    # ---- agentic tools' primitives
    def grep(self, pattern: str, max_hits: int = 30, include_archived: bool = False) -> list[tuple[str, int, str]]:
        """(doc_id, line number, line) for lines matching a case-insensitive regex."""
        if len(pattern) > 200 or re.search(r"\([^)]*[+*][^)]*\)[+*{]", pattern):
            # why: patterns come from the model; nested quantifiers like (a+)+ can backtrack for minutes (ReDoS)
            raise re.error("pattern too long or has nested quantifiers")
        rx = re.compile(pattern, re.I)
        out = []
        where = "" if include_archived else " WHERE status != 'archived'"
        for did, text in self.conn.execute(f"SELECT id, text FROM docs{where} ORDER BY id"):
            for n, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    out.append((did, n, line.strip()))
                    if len(out) >= max_hits:
                        return out
        return out

    def read_doc(self, doc_id: str) -> Doc | None:
        row = self.conn.execute("SELECT id, title, type, status, updated, text, meta FROM docs WHERE id = ?",
                                (doc_id,)).fetchone()
        if not row:
            return None
        return Doc(*row[:6], tuple(sorted(json.loads(row[6]).items())))

    def docs(self, include_archived: bool = False) -> list[Doc]:
        where = "" if include_archived else " WHERE status != 'archived'"
        ids = [r[0] for r in self.conn.execute(f"SELECT id FROM docs{where} ORDER BY id")]
        return [self.read_doc(i) for i in ids]

    def stats(self) -> dict:
        n_docs = self.conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        n_chunks, chars = self.conn.execute("SELECT COUNT(*), SUM(LENGTH(text)) FROM chunks").fetchone()
        return {"docs": n_docs, "chunks": n_chunks, "chunk_chars_avg": (chars or 0) / max(n_chunks, 1),
                "dense": self._vec, "embedder": self.embedder.name if self.embedder else None}
