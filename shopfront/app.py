"""Shopfront web app: `make run` then open http://localhost:8000

The assistant endpoint is a stub until Node 02 wires your agent in. Later nodes add
streaming (Node 17) and an approvals queue (Node 14).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import uuid

from shopfront import db, services
from shopfront.search import search_products

app = FastAPI(title="Shopfront")
STATIC = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _conn():
    return db.connect()


def _wrap(fn, *args):
    conn = _conn()
    try:
        return fn(conn, *args)
    except services.ShopError as e:
        raise HTTPException(status_code=404 if e.code == "NOT_FOUND" else 400, detail=e.to_dict())
    finally:
        conn.close()


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/products")
def products(q: str = "", page: int = 1):
    return _wrap(search_products, q, page)


@app.get("/api/products/{product_id}")
def product(product_id: int):
    return _wrap(services.get_product, product_id)


@app.get("/api/products/{product_id}/reviews")
def reviews(product_id: int):
    return _wrap(services.list_reviews, product_id)


# NOTE: no authentication anywhere in this demo app; customer_id comes from the request. Node 13
# (permissions & auth) is where that gets fixed. Don't copy this pattern.
@app.get("/api/orders/{order_id}")
def order(order_id: int):
    return _wrap(services.get_order, order_id)


class ChatIn(BaseModel):
    customer_id: int
    message: str
    session_id: str | None = None


_SESSIONS: dict = {}     # session_id -> SupportAssistant (in-memory: fine for a demo, lost on restart)


def _model_factory():
    """Separate function so tests can monkeypatch it with a scripted model."""
    import os
    from agentlab.config import api_key, resolve
    from agentlab.llm.registry import get_model
    alias = os.environ.get("ASSISTANT_MODEL", "fast")
    provider, _ = resolve(alias)
    if not api_key(provider):   # why: adapters create clients lazily, so check up front to fail with a clear 503
        raise RuntimeError(f"no API key configured for provider {provider!r} (alias {alias!r})")
    return get_model(alias)


@app.post("/api/assistant/chat")
def chat(body: ChatIn):
    from agentlab.assistant.support import SupportAssistant
    from agentlab.costs import Budget
    sid = body.session_id or uuid.uuid4().hex
    assistant = _SESSIONS.get(sid)
    if assistant is not None and assistant.customer_id != body.customer_id:
        raise HTTPException(status_code=403, detail="session belongs to a different customer")
    if assistant is None:
        try:
            model = _model_factory()
        except Exception as e:  # noqa: BLE001 - no key / no adapter: tell the operator, not a 500
            raise HTTPException(status_code=503, detail=f"Assistant model unavailable: {e}")
        # NOTE: customer_id comes from the request body; there is no auth in this demo (Node 13).
        assistant = SupportAssistant(model, db.connect(), body.customer_id,
                                     budget=Budget(limit_usd=0.25, label="web"))
        _SESSIONS[sid] = assistant
    return {"reply": assistant.chat(body.message).reply, "session_id": sid}
