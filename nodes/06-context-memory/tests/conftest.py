"""Fixtures for Node 06. The oracle models are rule-based stand-ins for an LLM that can only act on what is in
their context window. They let offline tests show WHICH strategies lose information, for free and
deterministically. They are not good assistants; they are good witnesses."""
import json
import re

import pytest

from agentlab.llm import fake
from agentlab.llm.types import ModelResponse, TextBlock, ToolResultBlock, Usage
from shopfront import db
from shopfront.seed import build

AMOUNTS = {4831: 2899, 4832: 4899}


@pytest.fixture(scope="session")
def template_db(tmp_path_factory):
    d = tmp_path_factory.mktemp("tmpl")
    path = d / "shop.db"
    build(path, out_dir=d)
    return path


@pytest.fixture()
def conn(template_db, tmp_path):
    path = db.snapshot(template_db, tmp_path / "shop.db")
    c = db.connect(path)
    yield c
    c.close()


def _visible(system, messages) -> str:
    parts = [system if isinstance(system, str) else " ".join(b.text for b in system)]
    for m in messages:
        for b in m.content:
            if isinstance(b, TextBlock):
                parts.append(b.text)
            elif isinstance(b, ToolResultBlock) and isinstance(b.content, str):
                parts.append(b.content)
    return "\n".join(parts)


class OracleModel:
    """Answers questions by searching the help center, and handles the long-conversation probes using ONLY its
    visible context: the system prompt, the messages it was sent (including summaries and notes)."""
    provider = "fake"
    model = "oracle"

    def __init__(self):
        self.calls = 0

    def complete(self, *, system, messages, tools=None, max_tokens=1024, **opts):
        self.calls += 1
        last = messages[-1]
        names = {t.name for t in tools or []}
        results = [b for b in last.content if isinstance(b, ToolResultBlock)]
        if results:
            return fake.say("Done: " + results[-1].content[:60] if isinstance(results[-1].content, str) else "Done.")
        text = [b.text for b in last.content if isinstance(b, TextBlock)][-1]
        seen = _visible(system, messages)
        low = text.lower()
        if "damaged order i mentioned" in low:
            m = re.search(r"order (\d{4}) arrived damaged", seen)
            if not m:
                return fake.say("Which order do you mean?")
            oid = int(m.group(1))
            return fake.call("issue_refund", order_id=oid, amount_cents=AMOUNTS[oid], reason="damaged")
        if "birthday order" in low and "refund" in low:
            m = re.search(r"Order (\d{4}) was a birthday present", seen)
            if not m:
                return fake.say("Which order is that?")
            oid = int(m.group(1))
            return fake.call("issue_refund", order_id=oid, amount_cents=AMOUNTS[oid], reason="changed_mind")
        if "call me" in low or "forget" in low:
            return fake.say("Sure.")
        if low.startswith("what's the status") or "arrive" in low:
            name = re.search(r"\[m\d+\] \(preference[^)]*\) .*?\bcalled (\w+)", seen)
            return fake.say(f"Hi {name.group(1)}! It was delivered." if name else "It was delivered.")
        if text.rstrip().endswith("?") and "search_help_center" in names:
            return fake.call("search_help_center", query=text)
        return fake.say("OK.")


class KeywordSummarizer:
    """A summariser that keeps the CUSTOMER's lines that mention a keyword (earlier summaries are carried forward:
    they arrive inside a customer message). Tool results and assistant text are dropped, as a good compaction prompt
    would drop re-fetchable content, so the summary stays small. Stands in for a GOOD compaction prompt."""
    provider = "fake"
    model = "kw-summarizer"
    KEYWORDS = ("damaged", "confirm", "birthday", "call it", "call me")

    def __init__(self):
        self.inputs: list[str] = []

    def complete(self, *, system, messages, tools=None, max_tokens=1024, **opts):
        src = messages[-1].text
        self.inputs.append(src)
        keep, speaker = [], None
        for ln in src.splitlines():
            for p in ("CUSTOMER:", "ASSISTANT", "TOOL RESULT"):
                if ln.startswith(p):
                    speaker = p
            if speaker == "CUSTOMER:" and any(k in ln.lower() for k in self.KEYWORDS) and ln not in keep:
                keep.append(ln.removeprefix("CUSTOMER: "))
        return ModelResponse([TextBlock("\n".join(keep) or "(nothing important)")], "end_turn",
                             Usage(input_tokens=len(src) // 4, output_tokens=20), self.model, self.provider)


class Extractor:
    """A memory extractor that proposes a nickname memory when the customer asks to be called something."""
    provider = "fake"
    model = "extractor"

    def __init__(self):
        self.calls: list[dict] = []

    def complete(self, *, system, messages, tools=None, max_tokens=1024, **opts):
        self.calls.append(opts)
        src = messages[-1].text
        out = []
        m = re.search(r"CUSTOMER: .*?(please call me (\w+))", src, re.I)
        if m:
            out.append({"kind": "preference", "text": f"Prefers to be called {m.group(2)}.",
                        "evidence": m.group(1), "supersedes": None})
        return fake.say(json.dumps({"memories": out}))


@pytest.fixture()
def oracle():
    return OracleModel


@pytest.fixture()
def keyword_summarizer():
    return KeywordSummarizer


@pytest.fixture()
def extractor():
    return Extractor
