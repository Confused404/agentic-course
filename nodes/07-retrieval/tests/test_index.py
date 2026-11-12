import pytest

from agentlab.retrieval.embed import HashEmbedder, get_embedder
from agentlab.retrieval.index import KBIndex, fts_query


@pytest.mark.parametrize("q", ['ELE-0048', 'what "is" this', 'not AND or NEAR(', "it's 2.4 GHz?", '***', ''])
def test_fts_query_is_always_valid(index, q):
    index.search_bm25(q, 3)              # must not raise sqlite3.OperationalError


def test_fts_query_quotes_tokens():
    assert fts_query('ELE-0048 not "xy"') == '"ELE-0048" OR "xy"', "quoted; stopwords and operators dropped"
    assert fts_query("what is it") == '"what" OR "is" OR "it"', "all stopwords: fall back to every token"


def test_bm25_finds_identifiers(index):
    hits = index.search_bm25("KIT-0011", 3)
    assert hits[0].doc_id == "product-KIT-0011"
    # with stopwords OR-ed in, short FAQ chunks full of "what"/"the"/"of" outranked the SKU page (TEXTBOOK §4)
    assert index.search_bm25("What's the capacity of KIT-0011?", 1)[0].doc_id == "product-KIT-0011"


def test_archived_excluded_unless_asked(index):
    q = "Trailhead Tent 3-person weight"
    assert all(h.status != "archived" for h in index.search(q, 10, "hybrid"))
    assert any(h.status == "archived" for h in index.search(q, 10, "bm25", include_archived=True))
    assert all(h.status != "archived" for h in index.search_dense(q, 10))
    assert len(index.search_dense(q, 30)) == 30, "pre-filtered KNN: excluding archived doesn't starve the list"


def test_dense_and_hybrid(index):
    d = index.search_dense("cast iron skillet seasoning", 5)
    assert len(d) == 5 and d[0].score >= d[-1].score
    h = index.search("cast iron skillet seasoning", 5, "hybrid")
    assert len(h) == 5 and len({x.chunk_id for x in h}) == 5
    with pytest.raises(ValueError):
        index.search("x", 3, "magic")


def test_bm25_only_index(corpus, tmp_path):
    idx = KBIndex(tmp_path / "b.db").build(corpus)
    assert idx.search("refund", 3, "hybrid"), "hybrid degrades to BM25 without an embedder"
    with pytest.raises(RuntimeError):
        idx.search_dense("refund", 3)


def test_build_is_cached_by_key(corpus, tmp_path, monkeypatch):
    import agentlab.retrieval.chunk as chunk_module
    p = tmp_path / "c.db"
    a = KBIndex(p, HashEmbedder(64)).build(corpus)
    real = chunk_module.chunk_markdown

    def boom(*a, **k):
        raise AssertionError("rebuilt although nothing changed")
    monkeypatch.setattr(chunk_module, "chunk_markdown", boom)
    KBIndex(p, HashEmbedder(64)).build(corpus)          # cached: must not chunk again
    monkeypatch.setattr(chunk_module, "chunk_markdown", real)
    key, n = a._meta("key"), a.stats()["chunks"]
    b = KBIndex(p, HashEmbedder(64)).build(corpus)
    assert b._meta("key") == key and b.stats()["chunks"] == a.stats()["chunks"]
    c = KBIndex(p, HashEmbedder(64)).build(corpus, max_chars=200)
    assert c._meta("key") != key and c.stats()["chunks"] > n, "new chunking -> rebuilt"


def test_rank_docs_dedupes(index):
    ranked = index.rank_docs("standing desk", 5, "bm25")
    assert len(ranked) == len(set(ranked)) <= 5


def test_grep_and_read(index):
    rows = index.grep(r"IP65")
    assert {d for d, _, _ in rows} >= {"product-LIG-0045", "product-LIG-0046"}
    assert all(not d.endswith(("-2024", "-2025")) for d, _, _ in rows)
    d = index.read_doc("help-refund-policy")
    assert d.title == "Refund policy" and "30 days" in d.text
    assert index.read_doc("nope") is None
    assert all(x.status != "archived" for x in index.docs())
    import re
    with pytest.raises(re.error):
        index.grep("(a+)+$")                     # nested quantifier: rejected, not run


def test_hash_embedder_is_deterministic_and_normalised():
    e = get_embedder("hash:64")
    a, b = e.embed(["flicker"]), e.embed(["flicker"])
    assert a == b and abs(sum(x * x for x in a[0]) - 1) < 1e-9
    with pytest.raises(ValueError):
        get_embedder("word2vec")
