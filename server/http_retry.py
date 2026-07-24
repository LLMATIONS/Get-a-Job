"""Bounded retry for the outbound API fetchers (Warcraft Logs, Blizzard).

Why this exists: both fetchers run on an hourly timer against third-party APIs
that sit behind Cloudflare, and both treat any exception as a hard failure that
exits non-zero. A single read timeout or upstream 502 is a blip rather than an
outage, but it failed the unit and paged the ops channel, roughly weekly.

Two separate defects produced that:

  * **No retry.** One unlucky request sank the whole hourly run even though the
    next attempt seconds later would have succeeded.
  * **A read timeout was not caught at all.** `urlopen` only wraps the *request*
    leg's OSError in `URLError`; a timeout while waiting on the response is
    raised from `http.client.getresponse()` as a bare `TimeoutError`, which
    sailed past `except urllib.error.URLError` and crashed with a raw traceback
    instead of the fetcher's clean one-line error. `TimeoutError` is an
    `OSError` subclass, so callers should catch `OSError` to cover both shapes.

Only transient shapes are retried (timeout, connection reset, 429, 5xx). An
auth failure, a 404, or a schema break still fails fast on the first attempt, so
a real breakage stays loud and does not sit behind 3 pointless retries.
"""
from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request

# Upstream-side statuses worth a second look. 4xx other than 429 means we asked
# wrong, and asking again identically will not help.
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
DEFAULT_ATTEMPTS = 3
DEFAULT_BACKOFF = 2.0
# Cap on a server-supplied Retry-After. The hourly timer is the real backstop,
# so a long cooldown is better spent failing and picking it up next tick than
# holding the unit open.
MAX_RETRY_AFTER = 30.0


def is_transient(exc: BaseException) -> bool:
    """True if `exc` is the kind of failure a retry could plausibly clear."""
    # HTTPError first: it subclasses URLError, which subclasses OSError.
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in RETRY_STATUS
    # URLError covers DNS/connect/reset; bare TimeoutError and ConnectionError
    # cover the response-read leg that urllib leaves unwrapped.
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError))


def _retry_after(exc: BaseException, fallback: float) -> float:
    """Honour a sane `Retry-After` on 429s, else use our own backoff."""
    if not isinstance(exc, urllib.error.HTTPError):
        return fallback
    raw = exc.headers.get("Retry-After") if exc.headers else None
    try:
        secs = float(raw)  # seconds form only; the HTTP-date form is rare here
    except (TypeError, ValueError):
        return fallback
    return max(0.0, min(secs, MAX_RETRY_AFTER))


def urlopen_retry(
    req: urllib.request.Request,
    *,
    timeout: float,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff: float = DEFAULT_BACKOFF,
    label: str = "http",
) -> bytes:
    """`urlopen(req, timeout=...)`, retried on transient failure, returning the body.

    The body is read inside the retry scope on purpose: a timeout can strike
    mid-read as easily as mid-connect, and a half-read response is not a result.
    The final exception is re-raised unchanged so callers keep their existing
    `HTTPError` / `OSError` handling (including reading `exc` for the error body).
    """
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:
            if attempt >= attempts or not is_transient(exc):
                raise
            delay = _retry_after(exc, backoff ** (attempt - 1))
            detail = getattr(exc, "code", None) or getattr(exc, "reason", None) or exc
            print(
                f"{label}: transient {type(exc).__name__} ({detail}); "
                f"retry {attempt}/{attempts - 1} in {delay:.1f}s",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)
    # Unreachable: the loop either returns or raises on the final attempt.
    raise AssertionError("urlopen_retry exhausted its loop without returning")
