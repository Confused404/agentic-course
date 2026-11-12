"""AGENT-OFF: chunk_markdown (YOU_DO task 2)."""
import re

from agentlab.retrieval.chunk import chunk_markdown
from agentlab.retrieval.corpus import Doc

TEXT = """Intro line before any heading.

# Refund policy

You can request a refund within 30 days.

## What cannot be refunded

- Gift cards.
- Cancelled orders.

### Exceptions

Damaged items: 60 days.

## Timing

Refunds over $200 are reviewed.
"""


def doc(text=TEXT, title="Refund policy", id="help-refund"):
    return Doc(id, title, "help", "current", "2026-01-01", text)


def body(c):
    return c.text.split("\n", 1)[1]


def test_sections_and_heading_paths():
    cs = chunk_markdown(doc())
    assert [c.heading for c in cs] == ["Refund policy", "Refund policy", "Refund policy > What cannot be refunded",
                                       "Refund policy > What cannot be refunded > Exceptions",
                                       "Refund policy > Timing"]
    assert "Intro line" in body(cs[0]) and "30 days" in body(cs[1])
    assert "Exceptions" not in cs[4].heading, "a new H2 drops the previous H3"


def test_heading_only_sections_are_not_emitted():
    cs = chunk_markdown(doc("# A\n\n## B\n\ntext under B\n", title="T"))
    assert [c.heading for c in cs] == ["A > B"]


def test_contextual_header():
    for c in chunk_markdown(doc()):
        assert c.text.split("\n", 1)[0] == f"[Refund policy] {c.heading}"


def test_ids_and_determinism():
    cs = chunk_markdown(doc())
    assert [c.id for c in cs] == [f"help-refund#{i}" for i in range(len(cs))]
    assert all(c.doc_id == "help-refund" and body(c).strip() for c in cs)
    assert chunk_markdown(doc()) == cs


def long_doc():
    paras = [f"Paragraph {i}. " + " ".join(f"word{i}_{j}" for j in range(30)) + "." for i in range(12)]
    return doc("# Big\n\n" + "\n\n".join(paras) + "\n", title="Big", id="big")


def test_size_limit_and_paragraph_splits():
    d = long_doc()
    cs = chunk_markdown(d, max_chars=400, overlap_chars=0)
    assert len(cs) > 3
    for c in cs:
        header = c.text.split("\n", 1)[0] + "\n"
        assert len(c.text) <= 400 + len(header)
        assert re.match(r"Paragraph \d+\.", body(c)), "split at paragraph boundaries when paragraphs fit"


def test_overlap_carries_the_boundary():
    cs = chunk_markdown(long_doc(), max_chars=400, overlap_chars=80)
    for prev, cur in zip(cs, cs[1:]):
        assert body(prev)[-40:] in body(cur), "the next piece starts with the tail of the previous one"
        header = cur.text.split("\n", 1)[0] + "\n"
        assert len(cur.text) <= 400 + len(header) + 80


def test_overlong_paragraph_splits_at_sentences_then_hard():
    sentences = " ".join(f"Sentence number {i} says something useful." for i in range(40))
    cs = chunk_markdown(doc("# S\n\n" + sentences + "\n\n" + "x" * 900 + "\n", title="S", id="s"),
                        max_chars=300, overlap_chars=0)
    for c in cs:
        assert len(body(c)) <= 300
    assert any(body(c).startswith("Sentence number") and body(c).rstrip().endswith(".") for c in cs)


import pytest  # noqa: E402


@pytest.mark.parametrize("max_chars,overlap", [(1200, 150), (300, 50), (150, 0)])
def test_coverage_on_the_whole_kb(corpus, max_chars, overlap):
    for d in corpus:
        cs = chunk_markdown(d, max_chars, overlap)
        for line in d.text.splitlines():
            line = line.strip()
            if line and len(line) <= max_chars and not re.match(r"^#{1,3} ", line):
                assert any(line in c.text for c in cs), (d.id, max_chars, line)
        for c in cs:
            header = c.text.split("\n", 1)[0] + "\n"
            assert len(c.text) <= max_chars + len(header) + overlap


def test_small_paragraphs_are_packed_not_split():
    d = doc("# A\n\nOne.\n\nTwo.\n\nThree.\n", title="T", id="t")
    assert len(chunk_markdown(d)) == 1, "a section that fits is one chunk"
    paras = [f"P{i} " + "x" * 115 for i in range(10)]          # ~120 chars each
    cs = chunk_markdown(doc("# B\n\n" + "\n\n".join(paras) + "\n", title="T", id="t"), max_chars=400,
                        overlap_chars=0)
    assert all(body(c).count("\n\n") >= 1 for c in cs[:-1]), "pack several paragraphs per piece"


def test_deep_headings_stay_in_the_body():
    cs = chunk_markdown(doc("# A\n\n#### not a section\n\ntext\n", title="T", id="t"))
    assert len(cs) == 1 and "#### not a section" in cs[0].text


def test_no_overlap_across_sections():
    long1 = "\n\n".join(f"alpha{i} " + "a" * 150 for i in range(5))
    cs = chunk_markdown(doc(f"# One\n\n{long1}\n\n# Two\n\nbeta text\n", title="T", id="t"),
                        max_chars=300, overlap_chars=100)
    two = [c for c in cs if c.heading == "Two"]
    assert len(two) == 1 and body(two[0]).strip() == "beta text"


def test_text_before_first_heading_uses_title():
    cs = chunk_markdown(doc("Preamble here.\n\n# Different H1\n\nbody\n", title="Doc Title", id="t"))
    assert cs[0].heading == "Doc Title" and cs[0].text.startswith("[Doc Title] Doc Title\n")
    assert cs[1].heading == "Different H1"
