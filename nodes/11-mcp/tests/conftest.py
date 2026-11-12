import hashlib

import pytest

from agentlab.llm import fake
from shopfront import db
from shopfront.seed import build


@pytest.fixture(scope="session")
def seeded(tmp_path_factory):
    d = tmp_path_factory.mktemp("tmpl")
    build(d / "shop.db", out_dir=d)
    return d


@pytest.fixture()
def db_path(seeded, tmp_path):
    return db.snapshot(seeded / "shop.db", tmp_path / "shop.db")


@pytest.fixture()
def conn(db_path):
    c = db.connect(db_path)
    yield c
    c.close()


@pytest.fixture()
def naive_pins_and_review(monkeypatch):
    """Deliberately NAIVE stand-ins for your AGENT-OFF pins/review functions (YOU_DO tasks 2-3), so the client and
    the lab can be tested first. Not solutions: the fingerprint ignores schemas and annotations, the diff ignores
    duplicates and removals, the review only knows one trick."""
    from agentlab.mcpkit import pins as P
    from agentlab.mcpkit import review as RV

    def fp(t):
        return hashlib.sha256(f"{t.name}\x00{t.description}".encode()).hexdigest()

    def diff(pinned, current):
        r = P.PinReport()
        for t in current:
            (r.unchanged if pinned.get(t.key) == fp(t) else r.changed if t.key in pinned else r.added).append(t.key)
        return r

    def review(tool, all_tools):
        return [RV.Finding("hidden_markup", "<important>")] if "<important>" in tool.description.lower() else []
    monkeypatch.setattr(P, "fingerprint", fp)
    monkeypatch.setattr(P, "diff_pins", diff)
    monkeypatch.setattr(P, "find_collisions", lambda tools: {})
    monkeypatch.setattr(RV, "review_tool", review)


class Gullible:
    """A fake support model that does whatever tool descriptions tell it to: the worst case for the lab.
    It looks up the order, follows any <IMPORTANT>/"before ANY refund" instruction in a quote tool's description by
    sending the customer's details, asks for a card number if a tool result says so, then replies."""
    provider, model = "fake", "gullible"

    def __init__(self, order_id=4822, want_quote=False):
        self.order_id, self.want_quote, self.turn, self.seen_tools = order_id, want_quote, 0, []

    def complete(self, *, system, messages, tools=None, max_tokens=1024, **opts):
        self.turn += 1
        names = {t.name: t for t in tools or []}
        self.seen_tools = sorted(names)
        last = fake.last_tool_results(messages)
        quote = next((t for n, t in names.items() if n.endswith("quote_shipping")), None)
        lookups = [n for n in sorted(names) if n.endswith("lookup_order")]
        # obeys descriptions: a lookup tool that says "prefer this" wins (that's what shadowing exploits)
        lookup = next((n for n in lookups if "prefer this" in names[n].description.lower()), lookups[0] if lookups
                      else None)
        if self.turn == 1 and lookup:
            r = fake.call(lookup, order_id=self.order_id)
        elif self.turn <= 2 and quote and ("<important>" in quote.description.lower()
                                           or "before any refund" in quote.description.lower() or self.want_quote):
            args = {"order_id": self.order_id, "destination_country": "CA"}
            if "notes" in quote.input_schema.get("properties", {}):
                # only what it has actually seen: the customer's signature in their message
                sig = [ln for ln in messages[0].text.splitlines() if ln.startswith("-- ")]
                args["notes"] = sig[0][3:] if sig else "no customer details available"
            r = fake.call(quote.name, **args)
        elif any("card number" in b.text for b in last):
            r = fake.say("To continue, please confirm your card number.")
        else:
            r = fake.say("Your order 4822 was delivered.")
        for i, b in enumerate(r.tool_calls):
            b.id = f"g{self.turn}_{i}"
        return r


@pytest.fixture()
def gullible():
    return Gullible
