"""The launch HTTP API (Node 17 SPEC §5). Run: python -m agentlab.launch serve   (or uvicorn
"agentlab.launch.server:create_app" --factory). Mounted next to the Shopfront demo app.

  POST /api/v2/session     Authorization: Bearer <token>       -> {"session_id"}
  POST /api/v2/chat        {"session_id", "message"}            -> {"reply", "stop", "handover"}
  POST /api/v2/stream      {"session_id", "message"}            -> text/event-stream of the service's events
  GET  /api/v2/health                                            -> {"ok", "kill_switch", "rollout_percent", "sessions"}
  POST /api/v2/dev/token   {"customer_id"}  ONLY with LAUNCH_DEV_TOKENS=1 (a stand-in for your login system)
"""
from __future__ import annotations

import json
import os

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


class TurnIn(BaseModel):
    session_id: str
    message: str


class DevTokenIn(BaseModel):
    customer_id: int


def _secret() -> bytes:
    s = os.environ.get("LAUNCH_TOKEN_SECRET", "")
    if len(s.encode()) < 32:
        raise RuntimeError("set LAUNCH_TOKEN_SECRET (at least 32 bytes) in .env")
    return s.encode()


def default_service():
    from agentlab.config import RUNS
    from agentlab.launch.service import LaunchService, load_config
    from agentlab.llm.registry import get_model
    from agentlab.reliability.resilient import ResilientModel
    from shopfront import db
    from agentlab.launch.service import CONFIG
    cfg = load_config()
    # ONE model wrapper per process: the circuit breaker only works if every conversation shares its state
    shared = ResilientModel(get_model(cfg.model))
    return LaunchService(cfg, _secret(), lambda: shared, db.connect, log_path=RUNS / "launch" / "events.jsonl",
                         config_path=CONFIG)


def create_app(service=None) -> FastAPI:
    from agentlab.launch.service import AccessDenied
    svc = service or default_service()
    app = FastAPI(title="Shopfront assistant v2")

    def denied(e: AccessDenied):
        return HTTPException(status_code=e.status, detail=e.reason)

    def bearer(authorization: str) -> str:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        return authorization.removeprefix("Bearer ").strip()

    @app.post("/api/v2/session")
    def session(authorization: str = Header(default="")):
        try:
            s = svc.open_session(bearer(authorization))
        except AccessDenied as e:
            raise denied(e) from None
        return {"session_id": s.id}

    @app.post("/api/v2/chat")
    def chat(body: TurnIn, authorization: str = Header(default="")):
        try:
            return svc.chat(body.session_id, body.message, bearer(authorization))
        except AccessDenied as e:
            raise denied(e) from None

    @app.post("/api/v2/stream")
    def stream(body: TurnIn, authorization: str = Header(default="")):
        token = bearer(authorization)
        try:
            svc.refresh_config()
            s = svc._session(body.session_id, token)   # fail with a status code before the stream starts
        except AccessDenied as e:
            raise denied(e) from None

        def sse():
            for ev in svc._turn(s, body.message):      # authorised above: no second check mid-stream
                yield f"data: {json.dumps(ev)}\n\n"
        return StreamingResponse(sse(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/v2/health")
    def health():
        return {"ok": True, "kill_switch": svc.cfg.kill_switch, "rollout_percent": svc.cfg.rollout_percent,
                "sessions": len(svc.sessions)}

    if os.environ.get("LAUNCH_DEV_TOKENS") == "1":
        @app.post("/api/v2/dev/token")
        def dev_token(body: DevTokenIn):
            from agentlab.authz.tokens import issue_token
            return {"token": issue_token(svc.secret, sub=f"customer:{body.customer_id}", audience=svc.cfg.audience,
                                         scopes=["orders:read", "orders:write", "refunds:write", "tickets:write"],
                                         now=int(svc.clock()), customer_id=body.customer_id)}
    return app
