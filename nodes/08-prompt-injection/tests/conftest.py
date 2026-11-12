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
    c = db.connect(db.snapshot(template_db, tmp_path / "shop.db"))
    yield c
    c.close()


@pytest.fixture()
def reference_policy(monkeypatch):
    """A reference flow_policy, so the AGENT-BUILT executors can be tested before you write yours (YOU_DO task 5).
    Tests of YOUR policy are in test_policy.py and don't use this."""
    from agentlab.security import policy as P

    def ref(call, ctx):
        if call.name in P.READ_ONLY:
            return P.Decision("allow", "read-only")
        if call.name not in P.SINKS:
            return P.Decision("deny", "unknown-tool")
        if call.name == "send_email":
            to = str(call.args.get("to", "")).strip().lower()
            allowed = {a.lower() for a in ctx.allowed_recipients}
            if to not in allowed:
                return P.Decision("deny", "recipient-not-allowed")
            text = f"{call.args.get('subject', '')} {call.args.get('body', '')}"
            if ({e.lower() for e in P.EMAIL_RX.findall(text)} - allowed) or P.URL_RX.search(text):
                return P.Decision("deny", "exfil-in-body")
            return P.Decision("allow", "ok")
        return P.Decision("ask" if call.tainted or ctx.tainted else "allow", "refund-needs-approval"
                          if call.tainted or ctx.tainted else "ok")
    monkeypatch.setattr(P, "flow_policy", ref)
    return ref
