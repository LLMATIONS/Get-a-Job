"""Regression check for the applications-channel cache. Run:

    GUILDNAMES_DB=/tmp/t.db DISCORD_WEBHOOK_URL=https://discord.invalid/api/webhooks/1/x \
        python3 server/test_channel_cache.py

The bug: a transient failure on the webhook GET cached the empty string, and
because the cache was keyed on `is not None` it stuck for the rest of the
process lifetime. With a bot token set neither caller falls back to the webhook,
so one blip silently killed application posts and trial pings until a restart.

No network: `urllib.request.urlopen` is swapped for a scripted fake.
"""
import io
import json
import os
import sys

os.environ.setdefault("GUILDNAMES_DB", "/tmp/hype-test-channel-cache.db")
os.environ.setdefault(
    "DISCORD_WEBHOOK_URL", "https://discord.invalid/api/webhooks/1/x")
os.environ.pop("DISCORD_APPLICATIONS_CHANNEL_ID", None)  # force the lazy path

import urllib.request  # noqa: E402

import app  # noqa: E402
import http_retry  # noqa: E402


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install(outcomes: list) -> dict:
    """Point urlopen at a scripted sequence; returns a call counter."""
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        outcome = outcomes[min(calls["n"], len(outcomes) - 1)]
        calls["n"] += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return _Resp(json.dumps(outcome).encode())

    urllib.request.urlopen = fake_urlopen
    return calls


def main() -> None:
    http_retry.time.sleep = lambda _s: None  # no backoff delay in tests
    assert not os.environ.get("DISCORD_APPLICATIONS_CHANNEL_ID"), \
        "test requires the lazy webhook path"

    # A transient failure must NOT be cached: it returns empty now, and the very
    # next call reaches the network again and succeeds.
    app._app_channel_id = None
    _install([TimeoutError("The read operation timed out")])
    assert app._applications_channel_id() == "", "failure should yield no channel"
    assert app._app_channel_id in (None, ""), "failure must not stick in the cache"

    calls = _install([{"channel_id": "123456789"}])
    assert app._applications_channel_id() == "123456789", "next call must retry"
    assert calls["n"] >= 1, "a failed lookup must not short-circuit later calls"

    # A success IS cached: no further network calls.
    calls = _install([{"channel_id": "999"}])
    assert app._applications_channel_id() == "123456789", "cached value should win"
    assert calls["n"] == 0, "a cached channel id must not re-fetch"

    # A response missing channel_id is likewise not sticky.
    app._app_channel_id = None
    _install([{"not_a_channel": True}])
    assert app._applications_channel_id() == ""
    _install([{"channel_id": "42"}])
    assert app._applications_channel_id() == "42", "empty result must not stick"

    # An explicit env channel id always wins and never touches the network.
    app.DISCORD_APPLICATIONS_CHANNEL_ID = "explicit"
    calls = _install([{"channel_id": "ignored"}])
    assert app._applications_channel_id() == "explicit"
    assert calls["n"] == 0, "explicit env id must not re-fetch"

    print("ok: channel-id cache")


if __name__ == "__main__":
    main()
    sys.exit(0)
