"""Embedders: text -> vectors (TEXTBOOK §4).

`HashEmbedder` is a deterministic, dependency-free stand-in (character n-gram feature hashing) so tests and CI run
offline. It captures spelling overlap, not meaning: "flicker" ≈ "flickering", but "buzz" is not near "hum". Use it to
test plumbing, never to judge dense retrieval. `FastEmbedder` runs a real embedding model locally via fastembed
(ONNX, CPU; `pip install -e '.[retrieval]'`; downloads the model once, ~100 MB).
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol


class Embedder(Protocol):
    name: str          # goes into the index cache key: change the model, rebuild the index
    dim: int

    def embed(self, texts: list[str], *, kind: str = "document") -> list[list[float]]:
        """kind: "document" or "query". Some models embed queries differently (instruction prefixes)."""
        ...


def _l2(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class HashEmbedder:
    def __init__(self, dim: int = 256, n: int = 3) -> None:
        self.dim, self.n, self.name = dim, n, f"hash{dim}-{n}"

    def embed(self, texts: list[str], *, kind: str = "document") -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for word in re.findall(r"\w+", t.lower()):
                w = f" {word} "
                for i in range(max(1, len(w) - self.n + 1)):
                    h = int.from_bytes(hashlib.blake2b(w[i:i + self.n].encode(), digest_size=4).digest(), "big")
                    v[h % self.dim] += 1.0 if (h >> 31) & 1 else -1.0
            out.append(_l2(v))
        return out


# Query/document prefixes some models were TRAINED with; leaving them out silently costs retrieval quality.
# Check the model card of anything you add. (bge v1.5 works without one; the instruction helps short queries.)
PREFIXES: dict[str, tuple[str, str]] = {
    "BAAI/bge-small-en-v1.5": ("Represent this sentence for searching relevant passages: ", ""),
    "BAAI/bge-base-en-v1.5": ("Represent this sentence for searching relevant passages: ", ""),
    "intfloat/multilingual-e5-large": ("query: ", "passage: "),
    "nomic-ai/nomic-embed-text-v1.5": ("search_query: ", "search_document: "),
}


class FastEmbedder:
    def __init__(self, model: str = "BAAI/bge-small-en-v1.5") -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as e:   # pragma: no cover - depends on the optional extra
            raise RuntimeError("dense retrieval needs fastembed: pip install -e '.[retrieval]'") from e
        self._m = TextEmbedding(model_name=model)
        self.query_prefix, self.doc_prefix = PREFIXES.get(model, ("", ""))
        self.name = f"fastembed:{model}"
        self.dim = len(next(iter(self._m.embed(["probe"]))))
        if self.query_prefix or self.doc_prefix:
            self.name += "+prefixed"

    def embed(self, texts: list[str], *, kind: str = "document") -> list[list[float]]:
        # why explicit prefixes: don't rely on a library to know your model's training format; the table is
        # visible, testable, and part of the index name (change it, rebuild)
        pre = self.query_prefix if kind == "query" else self.doc_prefix
        return [_l2([float(x) for x in v]) for v in self._m.embed([pre + t for t in texts])]


def get_embedder(spec: str) -> Embedder:
    """'hash' | 'hash:<dim>' | 'fastembed' | 'fastembed:<model name>'."""
    name, _, arg = spec.partition(":")
    if name == "hash":
        return HashEmbedder(int(arg) if arg else 256)
    if name == "fastembed":
        return FastEmbedder(arg or "BAAI/bge-small-en-v1.5")
    raise ValueError(f"unknown embedder {spec!r}: use hash[:dim] or fastembed[:model]")
