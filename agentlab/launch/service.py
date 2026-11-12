"""The production support assistant (Node 17 TEXTBOOK §4): everything the course built, composed behind one service.

  token (Node 13) -> rollout + kill switch -> SupportAssistant (prompt/tools v2, Node 05) with scoped tools
  -> ResilientModel (Node 14) -> streaming turns (this node) -> per-conversation budget with a graceful handover
  (Node 15 §7) -> one privacy-safe event per turn for monitoring (monitor.py)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import tomllib
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from agentlab import tracing
from agentlab.agent.loop import LoopConfig  # noqa: F401 - the same limits vocabulary as Node 02
from agentlab.config import ROOT
from agentlab.costs import Budget, BudgetExceeded
from agentlab.launch.streaming import stream_or_complete
from agentlab.llm.types import Message, ToolResultBlock, ToolUseBlock

CONFIG = ROOT / "config" / "launch.toml"


@dataclass
class LaunchConfig:
    model: str = "fast"
    prompt: str = "v2"
    tools: str = "v2"
    max_turns: int = 8
    budget_per_conversation_usd: float = 0.05
    handover_message: str = "I'm passing this to a colleague who can help."
    rollout_percent: float = 10.0
    rollout_salt: str = "launch"
    kill_switch: bool = False
    audience: str = "shopfront-assistant"
    required_scopes: frozenset[str] = frozenset({"orders:read"})
    max_message_chars: int = 4000                 # one huge message must not blow the conversation budget


def load_config(path: Path | str = CONFIG) -> LaunchConfig:
    d = tomllib.loads(Path(path).read_text())
    a, r, au = d.get("assistant", {}), d.get("rollout", {}), d.get("auth", {})
    cfg = LaunchConfig(model=a.get("model", "fast"), prompt=a.get("prompt", "v2"), tools=a.get("tools", "v2"),
                       max_turns=int(a.get("max_turns", 8)),
                       budget_per_conversation_usd=float(a.get("budget_per_conversation_usd", 0.05)),
                       handover_message=a.get("handover_message", LaunchConfig.handover_message),
                       rollout_percent=float(r.get("percent", 10)), rollout_salt=str(r.get("salt", "launch")),
                       kill_switch=bool(r.get("kill_switch", False)),
                       audience=au.get("audience", "shopfront-assistant"),
                       required_scopes=frozenset(au.get("required_scopes", ["orders:read"])),
                       max_message_chars=int(a.get("max_message_chars", 4000)))
    if not 0 <= cfg.rollout_percent <= 100 or cfg.max_turns < 1 or cfg.budget_per_conversation_usd <= 0:
        raise ValueError("launch.toml: percent in [0, 100], max_turns >= 1, budget > 0")
    return cfg


def in_rollout(customer_id: int, percent: float, salt: str) -> bool:
    """Stable per customer (the same customer always gets the same answer) and independent across salts."""
    h = int(hashlib.sha256(f"{salt}:{customer_id}".encode()).hexdigest()[:8], 16)
    return h % 10_000 < percent * 100


class AccessDenied(Exception):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status, self.reason = status, reason


@dataclass
class Session:
    id: str
    customer_id: int
    subject: str                    # the token's sub: later calls must present a token for the same subject
    assistant: Any
    budget: Budget
    model: Any
    conn: Any = None
    turns: int = 0
    handed_over: bool = False
    expires_at: int = 0


@dataclass
class LaunchService:
    cfg: LaunchConfig
    secret: bytes
    model_factory: Callable[[], Any]           # -> a ChatModel (production: ResilientModel(get_model(cfg.model)))
    conn_factory: Callable[[], Any]
    log_path: Path | None = None
    clock: Callable[[], float] = time.time
    config_path: Path | None = None            # re-read when it changes: the kill switch must not need a restart
    sessions: dict[str, Session] = field(default_factory=dict)
    _config_mtime: float = 0.0

    def refresh_config(self) -> None:
        if self.config_path is None:
            return
        m = Path(self.config_path).stat().st_mtime
        if m != self._config_mtime:
            self.cfg, self._config_mtime = load_config(self.config_path), m

    def _verify(self, token: str):
        from agentlab.authz import tokens as tokens_module
        try:
            return tokens_module.verify_token(token, self.secret, audience=self.cfg.audience,
                                              required_scopes=self.cfg.required_scopes, now=int(self.clock()))
        except tokens_module.TokenError as e:
            # why 401 vs 403: a bad token is "who are you?"; a missing scope is "I know you, and no"
            raise AccessDenied(403 if e.code == "insufficient_scope" else 401, e.code) from None

    def _prune(self) -> None:
        now = self.clock()
        for sid in [k for k, v in self.sessions.items() if now >= v.expires_at]:
            self._close(self.sessions.pop(sid))

    @staticmethod
    def _close(s: Session) -> None:
        try:
            if s.conn is not None:
                s.conn.close()
        except Exception:  # noqa: BLE001 - closing is best effort
            pass

    # ---------------------------------------------------------------- sessions
    def open_session(self, token: str) -> Session:
        from agentlab.authz.scoped import scoped_registry
        from agentlab.assistant.prompts import get_prompt
        from agentlab.assistant.support import SupportAssistant
        self.refresh_config()
        self._prune()
        p = self._verify(token)
        if p.customer_id is None:
            raise AccessDenied(403, "token is not bound to a customer")
        if self.cfg.kill_switch:
            raise AccessDenied(503, self.cfg.handover_message)
        if not in_rollout(p.customer_id, self.cfg.rollout_percent, self.cfg.rollout_salt):
            raise AccessDenied(404, "assistant not enabled for this customer yet")
        budget = Budget(limit_usd=self.cfg.budget_per_conversation_usd, label="conversation")
        model = self.model_factory()
        conn = self.conn_factory()
        a = SupportAssistant(model, conn, p.customer_id, budget=budget, max_turns=self.cfg.max_turns,
                             system_prompt=get_prompt(self.cfg.prompt), tool_variant=self.cfg.tools)
        # the customer comes from the verified token, never from a request field (confused deputy, Node 13), and the
        # model only sees the tools the token's scopes allow
        a.tools = scoped_registry(a.tools, p)
        s = Session(uuid.uuid4().hex, p.customer_id, p.sub, a, budget, model, conn=conn, expires_at=p.expires_at)
        self.sessions[s.id] = s
        return s

    def _session(self, session_id: str, token: str) -> Session:
        """A session id alone is not a credential (it ends up in URLs, logs, browser storage): every call must also
        present a valid token for the same subject."""
        p = self._verify(token)
        s = self.sessions.get(session_id)
        if s is None or p.sub != s.subject or p.customer_id != s.customer_id:
            raise AccessDenied(404, "unknown session")          # the same answer for "not yours": no probing
        if self.clock() >= s.expires_at:
            self._close(self.sessions.pop(session_id))
            raise AccessDenied(401, "session expired: its token did")
        return s

    # ---------------------------------------------------------------- turns
    def stream(self, session_id: str, text: str, token: str) -> Iterator[dict]:
        """Yield {"type": "delta", "text"} while the model writes, {"type": "tool", "name"} while tools run, and
        finally {"type": "done", "reply", "stop", "handover"}."""
        self.refresh_config()
        s = self._session(session_id, token)
        yield from self._turn(s, text)

    def _turn(self, s: Session, text: str) -> Iterator[dict]:
        if len(text) > self.cfg.max_message_chars:
            yield {"type": "done", "reply": "That message is too long for me; could you shorten it?",
                   "stop": "too_long", "handover": False}
            return
        if self.cfg.kill_switch or s.handed_over:
            yield {"type": "done", "reply": self.cfg.handover_message, "stop": "handover", "handover": True}
            return
        a = s.assistant
        t0, spent0 = self.clock(), s.budget.spent_usd
        user = Message.user(text)
        a.transcript.append(user)          # first: if anything fails, the record still shows what was asked
        base = len(a.messages)
        msgs = list(a.messages) + [user]
        stop, reply, error_kind, calls, budget_hit = "other", "", None, 0, False
        try:
            with tracing.agent_span("support-launch", customer=self._pseudo("customer", s.customer_id),
                                    session=self._pseudo("session", s.id)):
                while True:
                    if calls >= self.cfg.max_turns:
                        stop = "max_turns"
                        break
                    s.budget.check()
                    resp = None
                    with tracing.chat_span(s.model.provider, s.model.model) as span:
                        for ev in stream_or_complete(s.model, system=a.system, messages=msgs,
                                                     tools=a.tools.specs(), max_tokens=1024):
                            if ev["type"] == "text_delta" and ev.get("text"):
                                yield {"type": "delta", "text": ev["text"]}
                            elif ev["type"] == "response":
                                resp = ev["response"]
                        calls += 1
                        try:
                            cost = s.budget.charge(s.model.model, resp.usage, provider=s.model.provider)
                        except BudgetExceeded:
                            if resp.stop_reason == "end_turn" and resp.text.strip():
                                # the customer has already seen this complete answer: let it stand, and hand
                                # over from the next turn (the budget is spent)
                                budget_hit, cost = True, None
                            else:
                                raise
                        tracing.record_response(span, resp, cost)
                    msg = Message("assistant", list(resp.content))
                    msgs.append(msg)
                    if resp.stop_reason != "tool_use" or not resp.tool_calls:
                        stop = {"end_turn": "end_turn", "stop_sequence": "end_turn"}.get(resp.stop_reason,
                                                                                         resp.stop_reason)
                        reply = resp.text.strip()
                        break
                    results = []
                    for c in resp.tool_calls:
                        yield {"type": "tool", "name": c.name}
                        if c.parse_error:
                            results.append(ToolResultBlock(c.id, "Invalid JSON arguments; call the tool again.",
                                                           is_error=True))
                        else:
                            results.append(a.tools.execute(c))
                    msgs.append(Message("user", results))
        except BudgetExceeded:
            stop = "budget"
        except Exception as e:  # noqa: BLE001 - the customer gets a handover, the log gets the kind
            from agentlab.evals.runner import error_kind
            stop, error_kind = "error", error_kind(e)
        handover = stop != "end_turn" or not reply
        if budget_hit:
            s.handed_over = True             # this answer stands; the next turn goes to a person
        if handover:
            # why a handover, not an error page: Node 15 §7; and the session stays handed over
            s.handed_over = True
            reply = self.cfg.handover_message
        new = msgs[base + 1:]
        a.messages = msgs
        a.transcript += new
        s.turns += 1
        self._log({"ts": self.clock(), "session": self._pseudo("session", s.id),
                   "customer": self._pseudo("customer", s.customer_id), "turn": s.turns,
                   "stop": stop, "handover": handover, "budget_hit": budget_hit, "error_kind": error_kind,
                   "calls": calls, "tools": [b.name for m in new for b in m.content if isinstance(b, ToolUseBlock)],
                   "cost_usd": s.budget.spent_usd - spent0, "latency_s": self.clock() - t0})
        yield {"type": "done", "reply": reply, "stop": stop, "handover": handover}

    def chat(self, session_id: str, text: str, token: str) -> dict:
        out = {}
        for ev in self.stream(session_id, text, token):
            if ev["type"] == "done":
                out = ev
        return out

    def _pseudo(self, kind: str, value: Any) -> str:
        """A keyed hash: stable for joining log lines, not reversible without the secret (an unkeyed hash of a
        small id space is reversed by trying every id), and a logged session id can't be replayed."""
        return hmac.new(self.secret, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()[:16]

    def _log(self, event: dict) -> None:
        """One line per customer turn. No message text and no raw customer id: logs outlive conversations, and
        whoever reads them doesn't need either to run the service (privacy by default)."""
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a") as f:
            f.write(json.dumps(event) + "\n")
