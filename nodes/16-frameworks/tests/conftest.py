import os

import pytest

from shopfront import db
from shopfront.seed import build

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")


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


def _needs(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except NotImplementedError:
        pytest.skip("needs your AGENT-OFF implementation first (YOU_DO tasks 2-3)")
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture()
def needs_convert():
    from agentlab.frameworks import convert
    _needs(convert.to_course_messages, [])


@pytest.fixture()
def needs_nodes():
    from agentlab.frameworks import graph_nodes
    _needs(graph_nodes.tools_node, {"messages": []}, registry=None)
