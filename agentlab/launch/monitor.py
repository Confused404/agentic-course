"""Production monitoring for the launch (Node 17 TEXTBOOK §5): window metrics over the service's turn events, alert
rules, and a game-day drill that injects incidents with fakes (free) so you can tune the alerts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from agentlab.perf.economics import percentile


def window_metrics(events: list[dict], *, now: float, window_s: float) -> dict:
    """Over turn events with ts in (now - window_s, now]: conversations (distinct sessions), turns, error_rate,
    handover_rate, p95_latency_s, cost_per_conversation."""
    w = [e for e in events if now - window_s < e["ts"] <= now]
    sessions = {e["session"] for e in w}
    n = len(w)
    return {"conversations": len(sessions), "turns": n,
            "error_rate": sum(e.get("error_kind") is not None for e in w) / n if n else None,
            "handover_rate": sum(bool(e.get("handover")) for e in w) / n if n else None,
            "p95_latency_s": percentile([e["latency_s"] for e in w], 95) if n else None,
            "cost_per_conversation": sum(e.get("cost_usd", 0.0) for e in w) / len(sessions) if sessions else None}


ALERTS = (("error_rate", "error_rate_max"), ("handover_rate", "handover_rate_max"),
          ("p95_latency_s", "p95_latency_s_max"), ("cost_per_conversation", "cost_per_conversation_max"))


def firing(metrics: dict, cfg: dict) -> list[str]:
    """Alerts whose metric is above its `<metric>_max` in cfg; nothing fires below min_conversations (too little
    traffic to tell noise from an incident)."""
    if metrics["conversations"] < cfg.get("min_conversations", 5):
        return []
    out = []
    for metric, key in ALERTS:
        v, limit = metrics.get(metric), cfg.get(key)
        if v is not None and limit is not None and v > limit:
            out.append(f"{metric} {v:.3g} > {limit:g}")
    return out


@dataclass
class Phase:
    name: str
    minutes: int
    model: Callable[[], object]          # a fresh fake model per conversation


@dataclass
class DrillResult:
    timeline: list[tuple[float, str, list[str], dict]] = field(default_factory=list)   # (t, phase, alerts, metrics)
    events: list[dict] = field(default_factory=list)


def default_phases() -> list[Phase]:
    from agentlab.llm import fake
    from agentlab.reliability.faults import FaultyModel
    from agentlab.reliability.resilient import ResilientModel

    class Answer:
        provider, model = "fake", "claude-haiku-5-5"

        def complete(self, **kw):
            return fake.say("Your order is on its way and should arrive in 2 days.")

    class Looper(Answer):
        n = 0

        def complete(self, **kw):
            Looper.n += 1
            r = fake.call("search_help_center", query=f"refund policy {Looper.n}")
            r.tool_calls[0].id = f"loop{Looper.n}"
            return r

    counter = {"n": 0}

    def outage():
        counter["n"] += 1                     # why a counter: one seed per conversation, so `rate` means a rate
        return ResilientModel(FaultyModel(Answer(), rate=0.6, random_faults=("529", "503"), seed=counter["n"]),
                              max_attempts=2, sleep=lambda s: None)
    return [Phase("normal", 20, Answer), Phase("provider outage", 15, outage), Phase("recovered", 15, Answer),
            Phase("prompt regression: tool loop", 15, Looper), Phase("fixed", 15, Answer)]


def run_drill(make_service: Callable[[Callable[[], object], Callable[[], float]], object], token_for: Callable[[], str],
              cfg: dict, *, phases: list[Phase] | None = None, conversations_per_minute: int = 2,
              check_every_min: int = 5) -> DrillResult:
    """Simulated traffic through the real service with fake models and a fake clock (minutes are simulated)."""
    phases = phases or default_phases()
    t = [1_000_000.0]
    res = DrillResult()
    elapsed = 0
    for ph in phases:
        svc = make_service(ph.model, lambda: t[0])
        for minute in range(ph.minutes):
            for _ in range(conversations_per_minute):
                token = token_for()
                s = svc.open_session(token)
                svc.chat(s.id, "Where is my order?", token)
            t[0] += 60
            elapsed += 1
            if elapsed % check_every_min == 0:
                res.events = _read(svc)
                m = window_metrics(res.events, now=t[0], window_s=cfg.get("window_s", 600))
                res.timeline.append((elapsed, ph.name, firing(m, cfg), m))
    return res


def _read(svc) -> list[dict]:
    import json
    if svc.log_path is None or not svc.log_path.exists():
        return []
    return [json.loads(x) for x in svc.log_path.read_text().splitlines() if x.strip()]


def render_drill(r: DrillResult) -> str:
    rows = ["| minute | phase | conversations | error rate | handover | p95 s | $/conv | alerts |",
            "|---|---|---|---|---|---|---|---|"]

    def f(x, fmt):
        return "–" if x is None else format(x, fmt)
    for minute, phase, alerts, m in r.timeline:
        rows.append(f"| {minute} | {phase} | {m['conversations']} | {f(m['error_rate'], '.0%')} | "
                    f"{f(m['handover_rate'], '.0%')} | {f(m['p95_latency_s'], '.2f')} | "
                    f"{f(m['cost_per_conversation'], '.4f')} | {'; '.join(alerts) or ''} |")
    return "\n".join(rows) + "\n"
