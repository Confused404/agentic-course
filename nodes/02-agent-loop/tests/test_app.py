"""The web endpoint, with the model factory monkeypatched to a scripted model."""
from fastapi.testclient import TestClient

import shopfront.app as app_mod
from agentlab.llm.fake import ScriptedModel, say


def test_chat_endpoint_and_sessions(monkeypatch, template_db, tmp_path):
    from shopfront import db
    path = db.snapshot(template_db, tmp_path / "shop.db")
    monkeypatch.setattr(app_mod.db, "DEFAULT_DB", path)
    monkeypatch.setattr(app_mod, "_model_factory", lambda: ScriptedModel([say("hello there"), say("again")]))
    c = TestClient(app_mod.app)
    r = c.post("/api/assistant/chat", json={"customer_id": 9001, "message": "hi"})
    assert r.status_code == 200 and r.json()["reply"] == "hello there"
    sid = r.json()["session_id"]
    r2 = c.post("/api/assistant/chat", json={"customer_id": 9001, "message": "hi", "session_id": sid})
    assert r2.json()["reply"] == "again" and r2.json()["session_id"] == sid
    hijack = c.post("/api/assistant/chat", json={"customer_id": 9005, "message": "hi", "session_id": sid})
    assert hijack.status_code == 403, "a session id must not let another customer take over the session"


def test_chat_endpoint_without_model_is_503(monkeypatch):
    def boom():
        raise NotImplementedError("no adapter")
    monkeypatch.setattr(app_mod, "_model_factory", boom)
    r = TestClient(app_mod.app).post("/api/assistant/chat", json={"customer_id": 9001, "message": "hi"})
    assert r.status_code == 503
