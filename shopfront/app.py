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


@app.post("/api/assistant/chat")
def chat(body: ChatIn):
    # Node 02 replaces this with a call into agentlab.assistant. Keep the request/response shape.
    raise HTTPException(status_code=501, detail="Assistant not built yet. See nodes/02-agent-loop.")
