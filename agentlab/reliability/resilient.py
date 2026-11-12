"""A ChatModel wrapper that survives flaky providers (TEXTBOOK §2): retries with backoff for errors that can
succeed on retry, a fallback model when the primary keeps failing, and a circuit breaker so a dead provider costs
one fast failure instead of a minute of retries per call."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from agentlab.reliability import retry as retry_module


def retry_after_s(err: BaseException) -> float | None:
    """The server's requested wait, in seconds: an explicit `retry_after` attribute (our fakes), else the
    Retry-After header of the HTTP response the SDK error carries (anthropic/openai errors have `.response`).
    Only the delta-seconds form is used; an HTTP-date or garbage -> None (fall back to backoff)."""
    v = getattr(err, "retry_after", None)
    if v is None:
        headers = getattr(getattr(err, "response", None), "headers", None)
        try:
            v = headers.get("retry-after") if headers is not None else None
        except Exception:  # noqa: BLE001 - an odd response object must not break error handling
            v = None
    try:
        f = float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
    return f if f is not None and f >= 0 and f == f else None    # f == f: rejects NaN


class CircuitOpen(Exception):
    """The provider failed repeatedly; calls fail fast until the cooldown passes."""


@dataclass
class ResilientModel:
    inner: Any
    max_attempts: int = 4                      # tries per call, including the first
    base: float = 0.5
    cap: float = 20.0
    fallback: Any = None                       # another ChatModel (another provider, ideally)
    breaker_threshold: int = 5                 # consecutive failed CALLS (after retries) that open the circuit
    breaker_cooldown_s: float = 30.0
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    events: list[str] = field(default_factory=list)
    retries: int = 0
    _failed_calls: int = 0
    _opened_at: float | None = None

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts counts the first try too: it must be >= 1")
        self.provider, self.model = self.inner.provider, self.inner.model

    def _use(self, m: Any) -> None:
        # why mutate provider/model: the loop prices a call with model.model AFTER complete() returns; when the
        # fallback answered, it must be priced (and traced) as the fallback, not as the primary
        self.provider, self.model = m.provider, m.model

    def _breaker_open(self) -> bool:
        if self._opened_at is None:
            return False
        if self.clock() - self._opened_at >= self.breaker_cooldown_s:
            self._opened_at = None             # half-open: let one call through to probe
            self.events.append("breaker half-open")
            return False
        return True

    def complete(self, **kw: Any):
        if self._breaker_open():
            if self.fallback is not None:
                self._use(self.fallback)
                return self.fallback.complete(**kw)
            raise CircuitOpen(f"{self.inner.provider} circuit open after {self._failed_calls} failed calls")
        last: BaseException | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                r = self.inner.complete(**kw)
                self._failed_calls = 0
                self._use(self.inner)
                return r
            except Exception as e:  # noqa: BLE001 - classified below
                if not retry_module.is_retryable(e):
                    raise                       # a bug or a bad request: retrying wastes money and time
                last = e
                if attempt == self.max_attempts:
                    break
                d = retry_module.backoff_delay(attempt, base=self.base, cap=self.cap,
                                               retry_after=retry_after_s(e))
                self.retries += 1
                self.events.append(f"retry {attempt} after {type(e).__name__}, waiting {d:.2f}s")
                self.sleep(d)
        self._failed_calls += 1
        if self._failed_calls >= self.breaker_threshold:
            self._opened_at = self.clock()
            self.events.append("breaker opened")
        if self.fallback is not None:
            self.events.append(f"fallback after {type(last).__name__}")
            self._use(self.fallback)
            return self.fallback.complete(**kw)
        raise last

    def stream(self, **kw: Any):
        """Node 17: retry a stream only if it failed BEFORE its first event (after that, the customer has seen part
        of an answer, and a retry would show a different one); same backoff, fallback and breaker as complete()."""
        from agentlab.launch.streaming import stream_or_complete
        if not callable(getattr(type(self.inner), "stream", None)):
            r = self.complete(**kw)                 # the wrapped model can't stream: answer in one piece
            yield {"type": "response", "response": r}
            return
        if self._breaker_open():
            if self.fallback is not None:
                self._use(self.fallback)
                yield from stream_or_complete(self.fallback, **kw)
                return
            raise CircuitOpen(f"{self.inner.provider} circuit open after {self._failed_calls} failed calls")
        last: BaseException | None = None
        for attempt in range(1, self.max_attempts + 1):
            started = False
            try:
                for ev in self.inner.stream(**kw):
                    # "sent" means the customer could have seen something: text or a tool call, not message_start
                    started = started or ev.get("type") in ("text_delta", "tool_use_start", "tool_input_delta")
                    yield ev
                self._failed_calls = 0
                self._use(self.inner)
                return
            except Exception as e:  # noqa: BLE001 - classified below
                if started:
                    self._failed_calls += 1          # a failed call all the same: it counts toward the breaker
                    if self._failed_calls >= self.breaker_threshold:
                        self._opened_at = self.clock()
                        self.events.append("breaker opened")
                    raise
                if not retry_module.is_retryable(e):
                    raise
                last = e
                if attempt == self.max_attempts:
                    break
                d = retry_module.backoff_delay(attempt, base=self.base, cap=self.cap, retry_after=retry_after_s(e))
                self.retries += 1
                self.events.append(f"stream retry {attempt} after {type(e).__name__}, waiting {d:.2f}s")
                self.sleep(d)
        self._failed_calls += 1
        if self._failed_calls >= self.breaker_threshold:
            self._opened_at = self.clock()
            self.events.append("breaker opened")
        if self.fallback is not None:
            self.events.append(f"fallback after {type(last).__name__}")
            self._use(self.fallback)
            yield from stream_or_complete(self.fallback, **kw)
            return
        raise last
