"""AGENT-OFF: split documents into chunks (Node 07 YOU_DO task 2).

Read TEXTBOOK §3 first. Tests: nodes/07-retrieval/tests/test_chunk.py. `Chunk` is GIVEN; you write
`chunk_markdown` by hand. Every retriever in this node indexes your chunks, so their quality bounds everything.
"""
from __future__ import annotations

from dataclasses import dataclass

from agentlab.retrieval.corpus import Doc


@dataclass(frozen=True)
class Chunk:
    id: str              # f"{doc_id}#{n}", n = 0, 1, 2, ... in document order
    doc_id: str
    heading: str         # the heading path, e.g. "Refund policy > What cannot be refunded" (title if no heading)
    text: str            # what gets indexed and shown to the model: starts with the heading line (see below)


def chunk_markdown(doc: Doc, max_chars: int = 1200, overlap_chars: int = 150) -> list[Chunk]:
    """Split doc.text into chunks that follow the document's structure.

    Contract (the tests check each item):
    1. Sections: a line starting with 1-3 '#' characters and a space starts a new section. The heading path is the
       chain of enclosing headings joined with " > " (an H2 under an H1 gives "H1 > H2"; a new H2 replaces the
       previous H2 and drops any H3). Text before the first heading belongs to a section whose path is doc.title.
       A section whose only content is its heading line is not emitted on its own.
    2. Contextual header: every chunk's text starts with the line f"[{doc.title}] {heading}\n", then the body.
       why: a chunk saying "Hand-wash only." is useless without knowing WHICH product; the header makes each chunk
       self-describing for BM25, for embeddings, and for the model reading it.
    3. Size and packing: no chunk's text is longer than max_chars + len(header) + overlap_chars. A section whose
       body fits in max_chars is ONE chunk. A longer section is split into pieces, packing as many whole
       paragraphs (blank-line separated) into each piece as fit; a paragraph that alone is too long is split at
       line breaks, then at sentence ends (". ", "? ", "! "), and as a last resort every max_chars characters.
    4. Overlap: when a section is split, each piece after the first starts with the last overlap_chars characters
       of the previous piece's body (fewer only if the previous body is shorter, or if needed to respect the size
       limit), so a fact on a boundary appears whole in at least one chunk. Overlap never crosses from one
       section into the next. overlap_chars=0 means no overlap.
    5. Coverage: every non-empty line of doc.text that is no longer than max_chars (other than heading lines)
       appears, whole, in at least one chunk. Lines starting with 4+ '#' are body text, not headings.
    6. Ids are f"{doc.id}#{n}" in order, starting at 0; no chunk has an empty body; deterministic.
    """
    raise NotImplementedError("AGENT-OFF: write chunk_markdown (Node 07 YOU_DO task 2)")
