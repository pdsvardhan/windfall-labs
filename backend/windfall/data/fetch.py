"""Hardened price fetcher.

yfinance is the primary source. A bare request from a server IP already saw HTTP 429, so this
fetcher batches tickers, backs off exponentially on failure, and reports per-ticker success so the
pipeline can record honest coverage. A best-effort stooq fallback exists for single tickers.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import pandas as pd

from ..config import FETCH_BATCH_SIZE, FETCH_MAX_RETRIES, FETCH_SLEEP_SECONDS

_FIELDS = ["open", "high", "low", "close", "adj_close", "volume"]


@dataclass
class FetchReport:
    requested: int = 0
    ok: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        return (len(self.ok) / self.requested) if self.requested else 0.0


def _normalize_single(df: pd.DataFrame) -> pd.DataFrame | None:
    """Normalize a yfinance per-ticker frame to lowercase open/high/low/close/adj_close/volume."""
    if df is None or df.empty:
        return None
    df = df.rename(columns={
        "Open": "open", "High": "high", "Low": "low", "Close": "close",
        "Adj Close": "adj_close", "Volume": "volume",
    })
    if "adj_close" not in df.columns and "close" in df.columns:
        df["adj_close"] = df["close"]
    # Recent bars sometimes arrive without an adjusted close; fall back to close per-row.
    if "adj_close" in df.columns and "close" in df.columns:
        df["adj_close"] = df["adj_close"].fillna(df["close"])
    keep = [c for c in _FIELDS if c in df.columns]
    df = df[keep].copy()
    df = df.dropna(how="all")
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.index.name = "date"
    return df[~df.index.duplicated(keep="last")]


def _download_batch(tickers: list[str], start: str, end: str | None) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    out: dict[str, pd.DataFrame] = {}
    last_exc: Exception | None = None
    for attempt in range(FETCH_MAX_RETRIES):
        try:
            raw = yf.download(
                tickers, start=start, end=end, auto_adjust=False, actions=False,
                group_by="ticker", progress=False, threads=False,
            )
            if raw is None or len(raw) == 0:
                raise RuntimeError("empty frame")
            if isinstance(raw.columns, pd.MultiIndex):
                for t in tickers:
                    if t in raw.columns.get_level_values(0):
                        norm = _normalize_single(raw[t])
                        if norm is not None and not norm.empty:
                            out[t] = norm
            else:  # single ticker — flat columns
                norm = _normalize_single(raw)
                if norm is not None and not norm.empty:
                    out[tickers[0]] = norm
            if out:
                return out
            raise RuntimeError("no usable rows")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            wait = FETCH_SLEEP_SECONDS * (2 ** attempt)
            print(f"[fetch] batch attempt {attempt+1}/{FETCH_MAX_RETRIES} failed: {exc!r}; "
                  f"backing off {wait:.1f}s")
            time.sleep(wait)
    print(f"[fetch] batch giving up after {FETCH_MAX_RETRIES} tries: {last_exc!r}")
    return out


def fetch_prices(
    tickers: list[str], start: str = "2014-01-01", end: str | None = None,
) -> tuple[dict[str, pd.DataFrame], FetchReport]:
    """Fetch daily OHLCV for many tickers. Returns {ticker -> frame} and a coverage report."""
    report = FetchReport(requested=len(tickers))
    frames: dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), FETCH_BATCH_SIZE):
        batch = tickers[i:i + FETCH_BATCH_SIZE]
        got = _download_batch(batch, start, end)
        frames.update(got)
        report.ok.extend(got.keys())
        for t in batch:
            if t not in got:
                report.failed.append(t)
        done = min(i + FETCH_BATCH_SIZE, len(tickers))
        print(f"[fetch] {done}/{len(tickers)} tickers processed "
              f"({len(report.ok)} ok, {len(report.failed)} failed)")
        time.sleep(FETCH_SLEEP_SECONDS)
    return frames, report


def fetch_one(ticker: str, start: str = "2014-01-01", end: str | None = None) -> pd.DataFrame | None:
    """Fetch a single ticker (used for benchmarks). yfinance first, stooq as a fallback."""
    got = _download_batch([ticker], start, end)
    if ticker in got:
        return got[ticker]
    return _stooq_fallback(ticker, start, end)


def _stooq_fallback(ticker: str, start: str, end: str | None) -> pd.DataFrame | None:
    """Best-effort stooq daily CSV. NSE symbols map to <symbol>.in on stooq (not guaranteed)."""
    import requests

    sym = ticker.replace(".NS", "").lower()
    url = f"https://stooq.com/q/d/l/?s={sym}.in&i=d"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        from io import StringIO
        df = pd.read_csv(StringIO(resp.text))
        if df.empty or "Date" not in df.columns:
            return None
        df = df.rename(columns={
            "Date": "date", "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        })
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        df["adj_close"] = df["close"]
        df = df[(df.index >= pd.to_datetime(start))]
        if end:
            df = df[df.index <= pd.to_datetime(end)]
        return df[[c for c in _FIELDS if c in df.columns]]
    except Exception as exc:  # noqa: BLE001
        print(f"[fetch] stooq fallback failed for {ticker}: {exc!r}")
        return None
