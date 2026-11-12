"""GIVEN: fault injection for Node 14. Provider errors that look like the real SDKs' (status codes, Retry-After),
a model wrapper that injects them on schedule or at random, and a simulated process crash.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any


class ProviderError(Exception):
    """Base for injected provider errors. Real SDK errors carry .status_code (and headers); so do these."""
    status_code: int | None = None

    def __init__(self, message: str = "", retry_after: float | None = None) -> None:
        super().__init__(message or type(self).__name__)
        self.retry_after = retry_after


class RateLimitError(ProviderError):
    status_code = 429


class OverloadedError(ProviderError):
    status_code = 529           # Anthropic's "overloaded"


class InternalServerError(ProviderError):
    status_code = 500


class ServiceUnavailableError(ProviderError):
    status_code = 503


class APITimeoutError(ProviderError):
    status_code = None          # no response at all


class BadRequestError(ProviderError):
    status_code = 400           # your request is wrong: retrying won't help


class AuthenticationError(ProviderError):
    status_code = 401


class ContextWindowExceededError(ProviderError):
    status_code = 400


class Crash(BaseException):
    """A simulated process death (kill -9, OOM, a deploy). BaseException so no `except Exception` swallows it:
    the run just stops, mid-step, the way a real crash would."""


FAULTS = {"429": RateLimitError, "529": OverloadedError, "500": InternalServerError, "503": ServiceUnavailableError,
          "timeout": APITimeoutError, "400": BadRequestError, "401": AuthenticationError}


@dataclass
class FaultyModel:
    """Wraps a ChatModel. `plan` is a list consumed one entry per call: "ok" or a key of FAULTS (optionally
    "429:2.5" for a Retry-After of 2.5 s). After the plan runs out, each call fails with probability `rate`
    (chosen among `random_faults`), deterministically for a given seed."""
    inner: Any
    plan: list[str] = field(default_factory=list)
    rate: float = 0.0
    random_faults: tuple[str, ...] = ("429", "529", "500", "timeout")
    seed: int = 0
    calls: int = 0
    injected: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.provider, self.model = self.inner.provider, self.inner.model
        self._rng = random.Random(self.seed)

    def complete(self, **kw: Any):
        self.calls += 1
        step = self.plan.pop(0) if self.plan else (
            self._rng.choice(self.random_faults) if self._rng.random() < self.rate else "ok")
        if step != "ok":
            key, _, after = step.partition(":")
            self.injected.append(step)
            raise FAULTS[key](f"injected {key}", retry_after=float(after) if after else None)
        return self.inner.complete(**kw)
