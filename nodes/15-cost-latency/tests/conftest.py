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
def needs_prefix():
    from agentlab.perf import prefix
    _needs(prefix.first_divergence, {}, {})


@pytest.fixture()
def needs_economics():
    from agentlab.perf import economics
    _needs(economics.unit_economics, [], human_cost_usd=1.0)
