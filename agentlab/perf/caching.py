"""Cache layouts and a cache doctor (Node 15 TEXTBOOK §2).

CachePolicyModel wraps any ChatModel and lays out each request for prompt caching:
  off        no caching opts (providers that cache automatically still may: OpenAI-style prefix caching)
  auto       opts["cache"]=True: the adapter's automatic caching (Anthropic: top-level cache_control, whose
             breakpoint follows the end of the conversation)
  explicit   auto + an explicit breakpoint after the system prompt (tools + system cached even if the conversation
             part misses)
  timestamp  the classic anti-pattern, for the experiment: "Current time: <now>" at the START of the system prompt,
             with auto caching on. Every call's prefix differs right after the tools, and no cache entry ends
             there, so nothing is read back.
The doctor (diagnose) explains each call's cache result with prefix.first_divergence against the previous call.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Any, Callable

from agentlab.llm.types import TextBlock
from agentlab.perf import prefix as prefix_module
from agentlab.perf.pricing import cache_read_share, usage_from

POLICIES = ("off", "auto", "explicit", "timestamp")


def _text(system: Any) -> str:
    return system if isinstance(system, str) else "\n\n".join(b.text for b in system if isinstance(b, TextBlock))


class CachePolicyModel:
    def __init__(self, inner: Any, policy: str, *, now: Callable[[], dt.datetime] | None = None) -> None:
        if policy not in POLICIES:
            raise ValueError(f"cache policy {policy!r}: choose from {', '.join(POLICIES)}")
        self.inner, self.policy = inner, policy
        self._now = now or (lambda: dt.datetime.now(dt.timezone.utc))

    def __getattr__(self, name: str) -> Any:        # provider, model, records (RecordingModel), ...
        return getattr(self.inner, name)

    def complete(self, *, system, messages, tools=None, max_tokens: int = 1024, **opts):
        opts = dict(opts)
        opts.pop("cache", None)
        if self.policy != "off":
            opts["cache"] = True
        if self.policy == "explicit":
            system = [TextBlock(_text(system), cache=True)]     # breakpoint 1: after tools + system
        elif self.policy == "timestamp":
            # why this is wrong: dynamic content belongs at the END (or in the user turn), never before the stable
            # instructions; here it changes every call, so no earlier request's cache entry ever matches
            system = f"Current time: {self._now().isoformat(timespec='seconds')}\n\n{_text(system)}"
        return self.inner.complete(system=system, messages=messages, tools=tools, max_tokens=max_tokens, **opts)


def min_cacheable(record: dict) -> int:
    """Rough per-provider minimum prompt length for caching (TEXTBOOK §2, APPENDIX): Anthropic's 5.5 models cache from
    512 tokens; OpenAI-style automatic caching from about 1,024. Check your model's docs."""
    m = (record.get("model") or "").lower()
    return 512 if record.get("provider") == "anthropic" or "claude" in m else 1024


def _cache_requested(record: dict) -> bool:
    req = record.get("request") or {}
    sys_ = req.get("system")
    marked = isinstance(sys_, list) and any(b.get("cache") for b in sys_)
    return bool((req.get("opts") or {}).get("cache")) or marked


def diagnose(records: list[dict], *, min_cacheable_tokens: int | None = None, ttl_s: float = 300.0) -> list[dict]:
    """One row per call of ONE conversation (the records of one trial, in order): its cache read share and why.
    Each call is compared with the previous call to the SAME model: caches are per model, so a cascade has two.
    The prefix comparison says what COULD have been reused (an upper bound: a provider only reads back prefixes an
    earlier request wrote); when the provider read (almost) nothing anyway, the likely reasons are listed."""
    rows = []
    last_by_model: dict[str, dict] = {}
    for r in records:
        u = usage_from(r.get("usage"))
        share = cache_read_share(u) if r.get("usage") else None
        minimum = min_cacheable_tokens or min_cacheable(r)
        prev = last_by_model.get(r.get("model", ""))
        if prev is None:
            section, shared = "first", 0
            why = f"first call on {r.get('model')}: nothing to reuse yet" + \
                  (" (it wrote the cache)" if u.cache_write_tokens else "")
        else:
            d = prefix_module.first_divergence(prev["request"], r["request"])
            section, shared, why = d.section or "extends", d.shared_tokens, d.detail
            if shared < minimum:
                why += f" (shared prefix ~{shared} tokens: below the ~{minimum}-token minimum)"
            elif r.get("usage") and (share or 0) < 0.05:
                # the prefix allowed a hit and the provider read nothing: say why that can happen
                causes = []
                if not _cache_requested(r):
                    causes.append("caching wasn't requested (fine only on providers that cache automatically)")
                if (prev["request"].get("opts") or {}) != (r["request"].get("opts") or {}):
                    causes.append("request options changed (effort/thinking settings invalidate caches)")
                if r.get("t_start", 0) - prev.get("t_start", 0) > ttl_s:
                    causes.append(f"more than {ttl_s:.0f}s since the previous call (cache expired)")
                if r.get("answered_by") and prev.get("answered_by") and r["answered_by"] != prev["answered_by"]:
                    causes.append("a different model answered (provider-side fallback)")
                causes.append("routed to a different upstream server/provider, or no cache entry was written there")
                why += " BUT nothing was read: " + "; ".join(causes)
        rows.append({"seq": r.get("seq"), "model": r.get("model"), "prompt_tokens": u.total_input,
                     "cache_read_tokens": u.cache_read_tokens, "cache_write_tokens": u.cache_write_tokens,
                     "read_share": share, "section": section, "shared_tokens_est": shared, "why": why})
        if r.get("usage") is not None:
            last_by_model[r.get("model", "")] = r
    return rows


def cache_summary(conversations: list[list[dict]]) -> dict:
    """Totals over many conversations (each a list of call records)."""
    prompt = read = write = calls = 0
    sections: Counter = Counter()
    for recs in conversations:
        for row in diagnose(recs):
            calls += 1
            prompt += row["prompt_tokens"]
            read += row["cache_read_tokens"]
            write += row["cache_write_tokens"]
            sections[row["section"]] += 1
    return {"calls": calls, "prompt_tokens": prompt, "cache_read_tokens": read, "cache_write_tokens": write,
            "read_share": read / prompt if prompt else None, "divergences": dict(sections)}
