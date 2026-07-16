"""iter-23 #98: batch runners must dodge the 20:30 IST EOD cron and retry through the api bounce."""
import datetime as dt
import urllib.error

import pytest

from scripts import batch_client as bc


def _at(wd_date: str, hh: int, mm: int) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{wd_date} {hh:02d}:{mm:02d}:00")


# 2026-07-15 = Wednesday, 2026-07-18 = Saturday
def test_window_boundaries():
    assert not bc.in_cron_window(_at("2026-07-15", 20, 24))
    assert bc.in_cron_window(_at("2026-07-15", 20, 25))
    assert bc.in_cron_window(_at("2026-07-15", 20, 40))
    assert not bc.in_cron_window(_at("2026-07-15", 20, 55))


def test_weekend_is_not_a_window():
    assert not bc.in_cron_window(_at("2026-07-18", 20, 40))


def test_seconds_until_window_ends():
    assert bc.seconds_until_window_ends(_at("2026-07-15", 20, 45)) == pytest.approx(600.0)
    assert bc.seconds_until_window_ends(_at("2026-07-15", 12, 0)) == 0.0


@pytest.fixture(autouse=True)
def _outside_cron_window(monkeypatch):
    """Retry behavior must not depend on WHEN the suite runs (the window is a real sleep)."""
    monkeypatch.setattr(bc, "wait_out_cron_window", lambda **kw: 0.0)


def test_retries_through_bounce_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def flaky(url, payload, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionRefusedError("api bouncing")
        return {"ok": True}

    slept = []
    monkeypatch.setattr(bc, "_request", flaky)
    out = bc.post_json("http://x/api/backtests", {}, tries=5, backoff=1.0,
                       sleep=slept.append)
    assert out == {"ok": True} and calls["n"] == 3
    assert slept == [1.0, 1.0]


def test_4xx_raises_immediately_no_retry(monkeypatch):
    calls = {"n": 0}

    def bad_request(url, payload, timeout):
        calls["n"] += 1
        raise urllib.error.HTTPError(url, 400, "bad grid", None, None)

    monkeypatch.setattr(bc, "_request", bad_request)
    with pytest.raises(urllib.error.HTTPError):
        bc.post_json("http://x/api/backtests/batch", {}, tries=5, backoff=0.0,
                     sleep=lambda s: None)
    assert calls["n"] == 1


def test_exhausted_retries_raise_runtime_error(monkeypatch):
    monkeypatch.setattr(bc, "_request",
                        lambda u, p, t: (_ for _ in ()).throw(ConnectionRefusedError()))
    with pytest.raises(RuntimeError, match="still failing after 2 tries"):
        bc.get_json("http://x/health", tries=2, backoff=0.0, sleep=lambda s: None)
