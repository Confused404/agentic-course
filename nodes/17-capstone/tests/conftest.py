import pytest

from shopfront.seed import build


@pytest.fixture(scope="session")
def seeded(tmp_path_factory):
    d = tmp_path_factory.mktemp("tmpl")
    build(d / "shop.db", out_dir=d)
    return d


def _needs(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except NotImplementedError:
        pytest.skip("needs your AGENT-OFF implementation first (YOU_DO tasks 2-3)")
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture()
def needs_assemble():
    from agentlab.launch import stream
    _needs(stream.assemble, [], provider="x")


@pytest.fixture()
def needs_gate():
    import datetime as dt
    from agentlab.launch import gate
    _needs(gate.launch_decision, {}, [{"metric": "m", "op": ">=", "threshold": 0}],
           now=dt.datetime.now(dt.timezone.utc))
