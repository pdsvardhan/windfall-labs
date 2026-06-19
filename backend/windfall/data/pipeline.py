"""Pipeline orchestration: resolve a universe, fetch history, store it, update incrementally."""
from __future__ import annotations

import datetime as dt

from . import store
from .fetch import fetch_one, fetch_prices
from .universe import BENCHMARK_YF, get_universe


def _start_for_years(years: int) -> str:
    return (dt.date.today() - dt.timedelta(days=int(years * 365.25) + 5)).isoformat()


def load_universe(index: str = "nifty500", years: int = 12, include_benchmarks: bool = True,
                  skip_existing: bool = False) -> dict:
    """Full load: resolve constituents, fetch ~`years` of daily history, store, log coverage.

    With skip_existing=True, only tickers not already in the prices table are fetched (so
    expanding the universe doesn't re-download names already cached).
    """
    store.init_db()
    members = get_universe(index)
    store.record_universe(index, members)
    all_tickers = [m.ticker for m in members]
    start = _start_for_years(years)

    if skip_existing:
        have = set(store.available_tickers())
        tickers = [t for t in all_tickers if t not in have]
    else:
        tickers = all_tickers

    frames, report = fetch_prices(tickers, start=start)
    n_rows = store.upsert_prices(frames)
    store.log_fetch(index, report, start, None)

    bench_summary = {}
    if include_benchmarks:
        for name, sym in BENCHMARK_YF.items():
            df = fetch_one(sym, start=start)
            if df is not None and not df.empty:
                store.upsert_prices({sym: df})
                bench_summary[name] = {"ticker": sym, "rows": len(df)}

    return {
        "index": index, "years": years, "start": start, "members": len(all_tickers),
        "skip_existing": skip_existing, "fetched": len(tickers),
        "requested": report.requested, "ok": len(report.ok), "failed": len(report.failed),
        "coverage": round(report.coverage, 3), "rows_written": n_rows,
        "failed_sample": report.failed[:20], "benchmarks": bench_summary,
    }


def incremental_update(index: str = "nifty500") -> dict:
    """Fetch only new bars since the latest stored date (with a small overlap) and upsert."""
    store.init_db()
    cov = store.coverage_summary()
    last = cov.get("date_max")
    start = (dt.date.fromisoformat(last) - dt.timedelta(days=7)).isoformat() if last else \
        _start_for_years(12)
    members = get_universe(index)
    tickers = [m.ticker for m in members] + list(BENCHMARK_YF.values())
    frames, report = fetch_prices(tickers, start=start)
    n = store.upsert_prices(frames)
    store.log_fetch(f"{index}-incr", report, start, None)
    return {"index": index, "since": start, "rows_written": n,
            "ok": len(report.ok), "failed": len(report.failed)}
