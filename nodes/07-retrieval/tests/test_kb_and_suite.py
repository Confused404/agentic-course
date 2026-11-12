"""The knowledge base and the QA suite are data; these tests keep them honest (like Node 04's golden scripts)."""
import re
from pathlib import Path

from agentlab.retrieval.corpus import parse
from agentlab.retrieval.qa_eval import load_qa

NODE = Path(__file__).resolve().parents[1]


def test_kb_is_generated_and_current(tmp_path):
    from shopfront.kb import KB, build_kb
    build_kb(tmp_path / "kb")
    fresh = {p.name: p.read_text() for p in (tmp_path / "kb").glob("*.md")}
    committed = {p.name: p.read_text() for p in KB.glob("*.md")}
    assert fresh == committed, "data/kb is stale: run `python -m shopfront.kb`"


def test_kb_shape(corpus):
    assert len(corpus) > 200
    statuses = {d.status for d in corpus}
    assert statuses == {"current", "archived", "discontinued"}
    p = next(d for d in corpus if d.id == "product-OUT-0015")
    assert p.get("sku") == "OUT-0015" and p.type == "product" and not p.text.startswith("---")
    assert parse("no front matter", "x").id == "x"


def test_product_pages_agree_with_the_database(corpus, tmp_path):
    import sqlite3

    from shopfront.seed import build
    build(tmp_path / "s.db", out_dir=tmp_path)
    rows = sqlite3.connect(tmp_path / "s.db").execute("SELECT sku, price_cents, active FROM products").fetchall()
    by_id = {d.id: d for d in corpus}
    for sku, price, active in rows:
        d = by_id[f"product-{sku}"]
        assert f"${price / 100:.2f}" in d.text
        assert (d.status == "current") == bool(active)


def test_suite_labels_are_consistent(corpus):
    """Every gold doc exists; every answer_regex is satisfiable from the gold docs; every stale trap is real."""
    by_id = {d.id: d for d in corpus}
    tasks = load_qa(NODE / "evals")
    assert len(tasks) >= 35 and {t.split for t in tasks} == {"dev", "heldout"}
    for t in tasks:
        assert all(g in by_id for g in t.gold), t.id
        gold_text = "\n".join(by_id[g].text for g in t.gold).lower()
        for g in t.graders:
            if g["type"] == "answer_regex" and t.type not in ("multi_hop",):
                # yes/no patterns ("no", "not", ...) are about the answer's stance, not the source text
                if "\\bno\\b" not in g["pattern"] and "not" not in g["pattern"]:
                    assert re.search(g["pattern"], gold_text, re.I), (t.id, g["pattern"])
        if t.type == "stale":
            bad = [g["pattern"] for g in t.graders if g["type"] == "answer_not_regex"]
            archived = "\n".join(d.text for d in corpus if d.status == "archived")
            assert bad and all(re.search(b, archived, re.I) for b in bad), f"{t.id}: the archived trap must exist"
