"""Self-contained checks for the fetcher retry helper. Run: python3 server/test_http_retry.py

No network and no sleeping: `urllib.request.urlopen` and `time.sleep` are both
swapped for fakes, so the whole file runs in milliseconds.
"""
import io
import urllib.error
import urllib.request

import http_retry
from http_retry import is_transient, urlopen_retry

REQ = urllib.request.Request("https://example.invalid/x")


class _Resp(io.BytesIO):
    """Minimal stand-in for the urlopen context manager."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    hdrs = {"Retry-After": retry_after} if retry_after is not None else {}
    return urllib.error.HTTPError("https://example.invalid/x", code, "boom", hdrs, None)


def _run(outcomes: list, **kw) -> tuple[bytes, list, int]:
    """Drive urlopen_retry against a scripted sequence of results.

    Each entry is either bytes (a successful body) or an exception to raise.
    Returns (result, slept_delays, calls_made).
    """
    calls = {"n": 0}
    slept: list[float] = []

    def fake_urlopen(req, timeout=None):
        outcome = outcomes[calls["n"]]
        calls["n"] += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return _Resp(outcome)

    real_urlopen, real_sleep = urllib.request.urlopen, http_retry.time.sleep
    urllib.request.urlopen = fake_urlopen
    http_retry.time.sleep = slept.append
    try:
        out = urlopen_retry(REQ, timeout=5, **kw)
    finally:
        urllib.request.urlopen = real_urlopen
        http_retry.time.sleep = real_sleep
    return out, slept, calls["n"]


def main() -> None:
    # --- classification -----------------------------------------------------
    # The regression that started this: a read timeout arrives as a bare
    # TimeoutError, not wrapped in URLError.
    assert is_transient(TimeoutError("The read operation timed out"))
    assert is_transient(urllib.error.URLError("connection reset"))
    assert is_transient(ConnectionResetError())
    assert is_transient(_http_error(502))
    assert is_transient(_http_error(429))
    # Real breakage must stay loud and immediate.
    assert not is_transient(_http_error(401))
    assert not is_transient(_http_error(404))
    assert not is_transient(ValueError("bad json"))

    # --- retry behaviour ----------------------------------------------------
    # Clean first call: no retry, no sleep.
    out, slept, calls = _run([b"ok"])
    assert (out, slept, calls) == (b"ok", [], 1), (out, slept, calls)

    # The exact production failure: timeout, then success on the retry.
    out, slept, calls = _run([TimeoutError("The read operation timed out"), b"ok"])
    assert out == b"ok" and calls == 2 and slept == [1.0], (out, slept, calls)

    # Upstream 502 (the roster-sync failure shape) also clears on retry.
    out, slept, calls = _run([_http_error(502), b"ok"])
    assert out == b"ok" and calls == 2, (out, slept, calls)

    # Backoff grows, and attempts are bounded: 3 attempts => 2 sleeps.
    try:
        _run([TimeoutError(), TimeoutError(), TimeoutError()])
    except TimeoutError:
        pass
    else:
        raise AssertionError("exhausted retries should re-raise")
    _, slept, calls = _run([TimeoutError(), TimeoutError(), b"ok"])
    assert slept == [1.0, 2.0] and calls == 3, (slept, calls)

    # Non-transient failures are not retried at all.
    try:
        _run([_http_error(401), b"ok"])
    except urllib.error.HTTPError as exc:
        assert exc.code == 401
    else:
        raise AssertionError("401 should not be retried")

    # Retry-After is honoured on 429, and capped so we never hold the unit open.
    _, slept, _ = _run([_http_error(429, "5"), b"ok"])
    assert slept == [5.0], slept
    _, slept, _ = _run([_http_error(429, "9999"), b"ok"])
    assert slept == [http_retry.MAX_RETRY_AFTER], slept
    # A garbage or HTTP-date Retry-After falls back to our own backoff.
    _, slept, _ = _run([_http_error(429, "Wed, 21 Oct 2026 07:28:00 GMT"), b"ok"])
    assert slept == [1.0], slept

    print("ok: retry helper")


if __name__ == "__main__":
    main()
