"""Retry-through-bounce HTTP client for long-running host-side batch/research scripts (#98).

The weekday EOD refresh (cron 20:30 IST) STOPS and rebuilds the api container for its exclusive
DuckDB write window (adr-022), and the paper mark (20:40) follows it. A long sweep that POSTs
during that window dies mid-run with connection refused — this killed batch runners twice before
being filed as #98. Import this instead of raw urllib/requests in any script that expects to be
running for more than a few minutes:

    from scripts.batch_client import post_json
    out = post_json("http://127.0.0.1:8505/api/backtests", {"config": cfg, "save": False})

Behavior:
- If the wall clock is inside the cron window (Mon-Fri 20:25-20:55 server time) the call SLEEPS
  until the window ends before sending, so a request never straddles the stop/start. The box runs
  Asia/Kolkata, so local time == IST == the crontab's clock (documented assumption).
- Connection errors and 5xx retry with linear backoff (default 10 tries x 15s — rides out the
  ~20s bounce and a full image rebuild). 4xx raise immediately: they are the caller's bug, and
  retrying a 400 forever is how a runner hangs silently.
- The monthly paper rebalance (21:30 on the 1st) only curls the running api — no stop/start,
  no window needed.
"""
from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.request

CRON_WINDOW = (dt.time(20, 25), dt.time(20, 55))  # EOD refresh (20:30) + paper mark (20:40) + slack
_WEEKDAYS = range(0, 5)                            # Mon-Fri, matching `30 20 * * 1-5`


def in_cron_window(now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now()
    return now.weekday() in _WEEKDAYS and CRON_WINDOW[0] <= now.time() < CRON_WINDOW[1]


def seconds_until_window_ends(now: dt.datetime | None = None) -> float:
    now = now or dt.datetime.now()
    if not in_cron_window(now):
        return 0.0
    end = now.replace(hour=CRON_WINDOW[1].hour, minute=CRON_WINDOW[1].minute,
                      second=0, microsecond=0)
    return max(0.0, (end - now).total_seconds())


def wait_out_cron_window(sleep=time.sleep, now: dt.datetime | None = None) -> float:
    """Sleep until the EOD cron window ends; returns the seconds waited (0 if outside it)."""
    wait = seconds_until_window_ends(now)
    if wait > 0:
        print(f"[batch_client] inside the {CRON_WINDOW[0]:%H:%M}-{CRON_WINDOW[1]:%H:%M} EOD cron "
              f"window — waiting {wait:.0f}s for the api stop/start to finish (#98)")
        sleep(wait)
    return wait


def _request(url: str, payload: dict | None, timeout: float) -> dict:
    if payload is not None:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
    else:
        req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — localhost api
        return json.loads(resp.read().decode())


def _call(url: str, payload: dict | None, timeout: float, tries: int, backoff: float,
          sleep=time.sleep) -> dict:
    wait_out_cron_window(sleep=sleep)
    last: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            return _request(url, payload, timeout)
        except urllib.error.HTTPError as exc:
            if exc.code < 500:      # 4xx: caller's bug — do not retry into a silent hang
                raise
            last = exc
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            last = exc              # api down/bouncing — the case this module exists for
        if attempt < tries:
            print(f"[batch_client] {type(last).__name__} on {url} "
                  f"(attempt {attempt}/{tries}) — retrying in {backoff:.0f}s")
            sleep(backoff)
    raise RuntimeError(f"{url} still failing after {tries} tries: {last!r}") from last


def post_json(url: str, payload: dict, timeout: float = 900.0,
              tries: int = 10, backoff: float = 15.0, sleep=time.sleep) -> dict:
    return _call(url, payload, timeout, tries, backoff, sleep)


def get_json(url: str, timeout: float = 120.0,
             tries: int = 10, backoff: float = 15.0, sleep=time.sleep) -> dict:
    return _call(url, None, timeout, tries, backoff, sleep)
