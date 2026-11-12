import json
import threading

import pytest

from agentlab.llm import fake
from agentlab.llm.types import Usage
from shopfront import db
from shopfront.seed import build


@pytest.fixture(scope="session")
def seeded(tmp_path_factory):
    d = tmp_path_factory.mktemp("tmpl")
    build(d / "shop.db", out_dir=d)
    return d


@pytest.fixture()
def conn(seeded, tmp_path):
    c = db.connect(db.snapshot(seeded / "shop.db", tmp_path / "shop.db"))
    yield c
    c.close()


@pytest.fixture()
def naive_reconcile(monkeypatch):
    """A deliberately NAIVE reconcile (last writer wins, no conflicts, no retries logic), so the architectures can be
    tested before YOU_DO task 2. Not a solution: it's the version task 2 exists to replace."""
    from agentlab.multi import reconcile as R

    def naive(expected, reports):
        merged, got = {}, set()
        for r in reports:
            if r.ok:
                merged.update(r.items)
                got.add(r.shard)
        return R.Reconciled(merged, [s for s in expected if s not in got])
    monkeypatch.setattr(R, "reconcile", naive)


def stats_by_category(conn):
    from agentlab.multi.tasks import _stats
    out = {}
    for s in _stats(conn):
        out.setdefault(s["category"], {})[s["sku"]] = {"reviews": s["reviews"], "units_90d": s["units_90d"]}
    return out


@pytest.fixture()
def oracle_data(conn):
    return stats_by_category(conn)


class OracleWorker:
    """Thread-safe fake worker: reads its shard from the brief, lists products (a real tool call), then reports
    {SKU: {reviews, units_90d}} for its category. `skip` = shards that never report; `barrier` = make all workers
    meet (proves they run concurrently)."""
    provider, model = "fake", "oracle-worker"

    def __init__(self, data, skip=(), barrier=None, log=None):
        self.data, self.skip, self.barrier, self.log = data, set(skip), barrier, log if log is not None else []
        self.turn = 0

    def complete(self, *, system, messages, tools=None, max_tokens=1024, **opts):
        self.turn += 1
        shard = messages[0].text.rsplit("category '", 1)[1].split("'")[0]
        if self.turn == 1:
            self.log.append({"shard": shard, "first_messages": [m.text for m in messages],
                             "tools": sorted(t.name for t in tools or [])})
            if self.barrier:
                self.barrier.wait()
            r = fake.call("list_products", category=shard)
        elif self.turn == 2 and shard not in self.skip:
            r = fake.call("report", items=self.data[shard], notes="")
        else:
            r = fake.say("done")
        for i, b in enumerate(r.tool_calls):
            b.id = f"w{self.turn}_{i}"
        return r


@pytest.fixture()
def oracle_worker():
    return OracleWorker


class Sized:
    """Wraps a model and reports input tokens proportional to the prompt it was sent (for peak-context tests)."""

    def __init__(self, inner):
        self.inner, self.provider, self.model = inner, inner.provider, inner.model

    def complete(self, *, system, messages, **kw):
        r = self.inner.complete(system=system, messages=messages, **kw)
        r.usage = Usage(input_tokens=len(json.dumps([m.to_dict() for m in messages], default=str)) // 4,
                        output_tokens=10)
        return r


@pytest.fixture()
def sized():
    return Sized


@pytest.fixture()
def lock():
    return threading.Lock()
