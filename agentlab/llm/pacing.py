"""Wrappers the model registry puts around a ChatModel (GIVEN infrastructure, not part of any ticket).

- FreeTierPacer: OpenRouter's free (":free") models allow about 20 requests per minute per ACCOUNT. Parallel evals
  (Node 04), parallel workers (Node 10) or votes (Node 09, 13) would hit that in seconds and fail with 429s. The
  pacer spaces calls out, process-wide, so the course works on a free key without any setup. It doesn't help
  against the DAILY limit (50 requests, or 1,000 after $10 of credits): nothing but waiting does.
- WithDefaults: adds default options to every complete() call, e.g. `fallback_models` (OpenRouter's server-side
  fallback list, config/models.toml [fallbacks]). Options the caller passes explicitly win.

Both forward everything else (provider, model, stream, ...) to the wrapped model, so code that inspects the model
sees the real one.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

_LOCK = threading.Lock()
_STAMPS: deque[float] = deque()          # start times of recent free-model calls, shared by the whole process


def _wait_for_slot(rpm: int, clock: Callable[[], float], sleep: Callable[[float], None]) -> float:
    """Block until a call may start; returns the seconds spent waiting."""
    waited = 0.0
    while True:
        with _LOCK:
            now = clock()
            while _STAMPS and now - _STAMPS[0] >= 60.0:
                _STAMPS.popleft()
            if len(_STAMPS) < rpm:
                _STAMPS.append(now)
                return waited
            wait = 60.0 - (now - _STAMPS[0]) + 0.05
        sleep(wait)                       # outside the lock, so other threads can check too
        waited += wait


class _Wrapper:
    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def __getattr__(self, name: str) -> Any:     # provider, model, stream, last_dropped_opts, ...
        return getattr(self.inner, name)


class FreeTierPacer(_Wrapper):
    def __init__(self, inner: Any, rpm: int = 18, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        super().__init__(inner)
        self.rpm, self._clock, self._sleep = max(1, int(rpm)), clock, sleep
        self.last_wait_s = 0.0           # how long the last call waited for a slot (so latency reports can exclude it)

    def complete(self, **kw: Any):
        self.last_wait_s = _wait_for_slot(self.rpm, self._clock, self._sleep)
        return self.inner.complete(**kw)

    def stream(self, **kw: Any):
        self.last_wait_s = _wait_for_slot(self.rpm, self._clock, self._sleep)
        return self.inner.stream(**kw)


class WithDefaults(_Wrapper):
    def __init__(self, inner: Any, **defaults: Any) -> None:
        super().__init__(inner)
        self.defaults = defaults

    def complete(self, **kw: Any):
        return self.inner.complete(**{**self.defaults, **kw})

    def stream(self, **kw: Any):
        return self.inner.stream(**{**self.defaults, **kw})
