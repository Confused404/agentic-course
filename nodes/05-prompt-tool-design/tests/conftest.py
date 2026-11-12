import pytest

from shopfront import db
from shopfront.seed import build


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
