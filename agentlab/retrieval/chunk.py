"""AGENT-OFF: split documents into chunks (Node 07 YOU_DO task 2).

Read TEXTBOOK §3 first. Tests: nodes/07-retrieval/tests/test_chunk.py. `Chunk` is GIVEN; you write
`chunk_markdown` by hand. Every retriever in this node indexes your chunks, so their quality bounds everything.
"""
from __future__ import annotations

import re
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
    header = lambda h: f"[{doc.title}] {h}\n"  # noqa: E731
    sections: list[tuple[str, list[str]]] = []
    path: list[tuple[int, str]] = []
    cur_heading, cur_lines = doc.title, []
    for line in doc.text.splitlines():
        m = re.match(r"^(#{1,3}) (.+?)\s*$", line)
        if m:
            sections.append((cur_heading, cur_lines))
            level = len(m.group(1))
            path = [(lv, t) for lv, t in path if lv < level] + [(level, m.group(2))]
            cur_heading, cur_lines = " > ".join(t for _, t in path), []
        else:
            cur_lines.append(line)
    sections.append((cur_heading, cur_lines))

    chunks: list[Chunk] = []
    for heading, lines in sections:
        body = "\n".join(lines).strip()
        if not body:
            continue
        for piece in _split(body, max_chars, overlap_chars):
            chunks.append(Chunk(f"{doc.id}#{len(chunks)}", doc.id, heading, header(heading) + piece))
    return chunks


def _units(body: str, max_chars: int) -> list[tuple[str, str]]:
    """(separator, text) pieces in order: paragraphs ("\n\n"); an over-long paragraph becomes lines ("\n"); an
    over-long line becomes sentences (" "); an over-long sentence becomes max_chars slices (""). Keeping each
    piece's ORIGINAL separator is what makes coverage hold: rejoined pieces reproduce the source lines."""
    out: list[tuple[str, str]] = []
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            out.append(("\n\n", para))
            continue
        for j, line in enumerate(para.splitlines()):
            sep = "\n\n" if j == 0 else "\n"
            if len(line) <= max_chars:
                out.append((sep, line))
                continue
            for k, sent in enumerate(re.split(r"(?<=[.?!])\s+", line)):
                ssep = sep if k == 0 else " "
                while len(sent) > max_chars:
                    out.append((ssep, sent[:max_chars]))
                    sent, ssep = sent[max_chars:], ""
                if sent:
                    out.append((ssep, sent))
    return out


def _split(body: str, max_chars: int, overlap: int) -> list[str]:
    pieces, cur = [], ""
    for sep, u in _units(body, max_chars):
        if cur and len(cur) + len(sep) + len(u) > max_chars:
            pieces.append(cur)
            tail = cur[-overlap:] if overlap else ""
            cur = (tail + "\n\n" + u) if tail else u
            if len(cur) > max_chars + overlap:      # keep the size bound: trim the overlap, never the new text
                cur = cur[len(cur) - (max_chars + overlap):]
        else:
            cur = (cur + sep + u) if cur else u
    if cur:
        pieces.append(cur)
    return pieces
