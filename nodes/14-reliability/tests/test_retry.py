"""AGENT-OFF: is_retryable, backoff_delay (YOU_DO task 2)."""
import pytest

from agentlab.reliability import faults as F
from agentlab.reliability.retry import backoff_delay, is_retryable


@pytest.mark.parametrize("err,ok", [
    (F.RateLimitError(), True), (F.OverloadedError(), True), (F.InternalServerError(), True),
    (F.ServiceUnavailableError(), True), (F.APITimeoutError(), True),
    (F.BadRequestError(), False), (F.AuthenticationError(), False), (F.ContextWindowExceededError(), False),
    (TimeoutError(), True), (ConnectionResetError(), True), (ValueError("bug"), False), (KeyError("x"), False),
])
def test_classification(err, ok):
    assert is_retryable(err) is ok


@pytest.mark.parametrize("status,ok", [(408, True), (409, True), (429, True), (500, True), (502, True),
                                       (503, True), (504, True), (529, True), (400, False), (401, False),
                                       (404, False), (413, False), (422, False), (501, False)])
def test_status_codes(status, ok):
    class HTTPError(Exception):
        pass
    e = HTTPError()
    e.status_code = status
    assert is_retryable(e) is ok


def test_status_wins_over_name():
    class TimeoutWithStatus(Exception):
        status_code = 400
    assert not is_retryable(TimeoutWithStatus())

    class Weird(Exception):
        status = 503
    assert is_retryable(Weird())

    class BoolStatus(Exception):
        status_code = True
    assert not is_retryable(BoolStatus()), "a bool is not a status code"


def test_never_retry_process_level_exits():
    assert not is_retryable(F.Crash()) and not is_retryable(KeyboardInterrupt()) and not is_retryable(SystemExit())


def test_backoff_full_jitter():
    assert backoff_delay(1, base=0.5, rand=lambda: 1.0) == 0.5
    assert backoff_delay(3, base=0.5, rand=lambda: 1.0) == 2.0
    assert backoff_delay(3, base=0.5, rand=lambda: 0.25) == 0.5
    assert backoff_delay(20, base=0.5, cap=30, rand=lambda: 1.0) == 30.0, "capped"
    assert backoff_delay(2, rand=lambda: 0.0) == 0.0
    assert backoff_delay(10_000, base=0.5, cap=30, rand=lambda: 1.0) == 30.0, "no OverflowError for huge attempts"


def test_retry_after_wins_but_is_capped():
    assert backoff_delay(1, retry_after=7.0, rand=lambda: 0.0) == 7.0
    assert backoff_delay(1, retry_after=120.0, cap=30) == 30.0
    assert backoff_delay(1, retry_after=0.0, rand=lambda: 1.0) == 0.0
    assert backoff_delay(2, retry_after=-1, base=1.0, rand=lambda: 1.0) == 2.0, "negative: ignore it"


def test_bad_arguments():
    for kw in ({"attempt": 0}, {"attempt": 1, "base": 0}, {"attempt": 1, "cap": -1}):
        with pytest.raises(ValueError):
            backoff_delay(**kw)
