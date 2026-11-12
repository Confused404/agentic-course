import pytest

from agentlab.retrieval.corpus import load_corpus


@pytest.fixture(scope="session")
def corpus():
    return load_corpus()


@pytest.fixture(scope="session")
def index(corpus, tmp_path_factory):
    """BM25 + hash-embedding index over the real KB. Hash embeddings test the plumbing, not semantic quality."""
    from agentlab.retrieval.embed import HashEmbedder
    from agentlab.retrieval.index import KBIndex
    return KBIndex(tmp_path_factory.mktemp("kb") / "index.db", HashEmbedder(128)).build(corpus)
