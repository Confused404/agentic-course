"""When to retry a failed model call, and how long to wait. AGENT-OFF (reference solution): written by hand in Node 14 YOU_DO task 2.

Tests: nodes/14-reliability/tests/test_retry.py. Read TEXTBOOK §2 first. Standard library only.
"""
from __future__ import annotations

import random
from typing import Callable

RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504, 529})
RETRYABLE_NAMES = ("RateLimit", "Overloaded", "Timeout", "Connection", "InternalServer", "ServiceUnavailable")


def is_retryable(err: BaseException) -> bool:
    """Is a retry likely to succeed? Contract (each line is tested):

    1. Never retry BaseExceptions that aren't Exceptions (KeyboardInterrupt, SystemExit, a simulated Crash).
    2. If the error has an int attribute `status_code` (or else `status`; a bool is not a status code): retryable
       iff it's in RETRYABLE_STATUS.
       This wins over the name (a "TimeoutError" with status 400 is a bad request).
    3. Otherwise: builtin TimeoutError and ConnectionError (and their subclasses) are retryable; so is any error
       whose class name contains one of RETRYABLE_NAMES.
    4. Everything else is not retryable (a bug, a bad request, an auth error: retrying wastes money and time).
    """
    if not isinstance(err, Exception):
        return False
    for attr in ("status_code", "status"):
        v = getattr(err, attr, None)
        if isinstance(v, int) and not isinstance(v, bool):
            return v in RETRYABLE_STATUS
    if isinstance(err, (TimeoutError, ConnectionError)):
        return True
    return any(n in type(err).__name__ for n in RETRYABLE_NAMES)


def backoff_delay(attempt: int, *, base: float = 0.5, cap: float = 30.0, retry_after: float | None = None,
                  rand: Callable[[], float] = random.random) -> float:
    """Seconds to wait before retry number `attempt` (1 = the first retry). Contract:

    1. attempt < 1 -> ValueError. base and cap must be > 0 -> else ValueError.
    2. If the server said how long to wait (retry_after is not None and >= 0): wait exactly that, capped at `cap`.
    3. Otherwise "full jitter": rand() * min(cap, base * 2 ** (attempt - 1)). why jitter: when many clients fail
       together, waiting the same time makes them retry together, and fail together again.
    4. Never negative; never above cap; no OverflowError for a huge attempt number.
    """
    if attempt < 1:
        raise ValueError("attempt starts at 1")
    if base <= 0 or cap <= 0:
        raise ValueError("base and cap must be positive")
    if retry_after is not None and retry_after >= 0:
        return min(float(retry_after), cap)       # why: the server knows its own load better than our formula
    return max(0.0, min(cap, rand() * min(cap, base * 2.0 ** min(attempt - 1, 60))))
