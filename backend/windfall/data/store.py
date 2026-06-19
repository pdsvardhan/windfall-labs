"""DuckDB store: prices, universe membership, fetch log, plus read helpers.

Adjusted OHLC is derived on read via factor = adj_close / close, so we store one clean row per
(date, ticker) and never duplicate adjusted columns.
"""
from __future__ import annotations

import datetime as dt
import threading

import duckdb
import pandas as pd

from ..config import DB_PATH, ensure_dirs

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    date DATE NOT NULL,
    ticker VARCHAR NOT NULL,
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
    adj_close DOUBLE, volume DOUBLE,
    PRIMARY KEY (date, ticker)
);
CREATE TABLE IF NOT EXISTS universe_members (
    index_name VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    ticker VARCHAR NOT NULL,
    name VARCHAR, sector VARCHAR, isin VARCHAR,
    added_on DATE,
    PRIMARY KEY (index_name, ticker)
);
CREATE TABLE IF NOT EXISTS fetch_log (
    run_at TIMESTAMP, universe VARCHAR,
    requested INTEGER, ok INTEGER, failed INTEGER, coverage DOUBLE,
    date_start DATE, date_end DATE
);
"""


_CON: duckdb.DuckDBPyConnection | None = None
_LOCK = threading.RLock()


class _ConnProxy:
    """Forwards to a process-wide singleton connection; close() is a no-op.

    DuckDB rejects opening the same file twice in one process with a different configuration
    (e.g. read-only vs read-write). A single shared read-write connection avoids that entirely;
    a re-entrant lock serializes mutations for the threadpool. read_only is accepted for
    backward-compatibility but ignored.
    """

    def __init__(self, real: duckdb.DuckDBPyConnection):
        self._real = real

    def execute(self, *a, **k):
        with _LOCK:
            return self._real.execute(*a, **k)

    def register(self, *a, **k):
        with _LOCK:
            return self._real.register(*a, **k)

    def close(self):  # no-op: the singleton lives for the process lifetime
        pass

    def __getattr__(self, name):
        return getattr(self._real, name)


def connect(read_only: bool = False) -> _ConnProxy:  # noqa: ARG001 — read_only kept for compat
    global _CON
    with _LOCK:
        if _CON is None:
            ensure_dirs()
            _CON = duckdb.connect(str(DB_PATH))
            _CON.execute(_SCHEMA)
        return _ConnProxy(_CON)


def init_db() -> None:
    connect()


def upsert_prices(frames: dict[str, pd.DataFrame]) -> int:
    """Insert/replace OHLCV rows. `frames` maps ticker -> df indexed by date."""
    if not frames:
        return 0
    long_parts = []
    for ticker, df in frames.items():
        d = df.reset_index().rename(columns={"index": "date"})
        if "date" not in d.columns:
            d = d.rename(columns={d.columns[0]: "date"})
        d["ticker"] = ticker
        long_parts.append(d)
    long = pd.concat(long_parts, ignore_index=True)
    for col in ["open", "high", "low", "close", "adj_close", "volume"]:
        if col not in long.columns:
            long[col] = pd.NA
    long["date"] = pd.to_datetime(long["date"]).dt.date
    long = long[["date", "ticker", "open", "high", "low", "close", "adj_close", "volume"]]

    con = connect()
    try:
        con.register("incoming", long)
        con.execute(
            """
            INSERT INTO prices
            SELECT date, ticker, open, high, low, close, adj_close, volume FROM incoming
            ON CONFLICT (date, ticker) DO UPDATE SET
                open = excluded.open, high = excluded.high, low = excluded.low,
                close = excluded.close, adj_close = excluded.adj_close, volume = excluded.volume
            """
        )
        n = len(long)
    finally:
        con.close()
    return n


def record_universe(index_name: str, members) -> None:
    rows = [
        {"index_name": index_name, "symbol": m.symbol, "ticker": m.ticker,
         "name": m.name, "sector": m.sector, "isin": m.isin, "added_on": dt.date.today()}
        for m in members
    ]
    df = pd.DataFrame(rows)
    con = connect()
    try:
        con.register("u", df)
        con.execute(
            """
            INSERT INTO universe_members
            SELECT index_name, symbol, ticker, name, sector, isin, added_on FROM u
            ON CONFLICT (index_name, ticker) DO UPDATE SET
                symbol = excluded.symbol, name = excluded.name,
                sector = excluded.sector, isin = excluded.isin
            """
        )
    finally:
        con.close()


def log_fetch(universe: str, report, start: str, end: str | None) -> None:
    con = connect()
    try:
        con.execute(
            "INSERT INTO fetch_log VALUES (?,?,?,?,?,?,?,?)",
            [dt.datetime.now(), universe, report.requested, len(report.ok),
             len(report.failed), report.coverage, start, end or str(dt.date.today())],
        )
    finally:
        con.close()


# ── read helpers ───────────────────────────────────────────────────────────────

def available_tickers() -> list[str]:
    con = connect(read_only=True)
    try:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM prices ORDER BY ticker").fetchall()]
    finally:
        con.close()


def universe_tickers(index_name: str = "nifty500") -> list[str]:
    con = connect(read_only=True)
    try:
        return [r[0] for r in con.execute(
            "SELECT ticker FROM universe_members WHERE index_name = ? ORDER BY ticker",
            [index_name]).fetchall()]
    finally:
        con.close()


def sector_map(index_name: str = "nifty500") -> dict[str, str]:
    con = connect(read_only=True)
    try:
        rows = con.execute(
            "SELECT ticker, sector FROM universe_members WHERE index_name = ?",
            [index_name]).fetchall()
        return {t: (s or "Unknown") for t, s in rows}
    finally:
        con.close()


def load_prices(
    tickers: list[str] | None = None, start: str | None = None, end: str | None = None,
    adjusted: bool = True,
) -> pd.DataFrame:
    """Return a long OHLCV frame. When adjusted, OHLC are scaled by adj_close/close."""
    con = connect(read_only=True)
    try:
        q = "SELECT date, ticker, open, high, low, close, adj_close, volume FROM prices WHERE 1=1"
        params: list = []
        if tickers:
            q += f" AND ticker IN ({','.join(['?'] * len(tickers))})"
            params += list(tickers)
        if start:
            q += " AND date >= ?"; params.append(start)
        if end:
            q += " AND date <= ?"; params.append(end)
        q += " ORDER BY date, ticker"
        df = con.execute(q, params).fetchdf()
    finally:
        con.close()
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    if adjusted:
        factor = (df["adj_close"] / df["close"]).replace([float("inf")], 1.0).fillna(1.0)
        for col in ["open", "high", "low"]:
            df[col] = df[col] * factor
        df["close"] = df["adj_close"]
    return df


def price_panel(
    field: str = "close", tickers: list[str] | None = None,
    start: str | None = None, end: str | None = None, adjusted: bool = True,
) -> pd.DataFrame:
    """Wide panel: index=date, columns=ticker, values=field."""
    long = load_prices(tickers, start, end, adjusted=adjusted)
    if long.empty:
        return pd.DataFrame()
    return long.pivot(index="date", columns="ticker", values=field).sort_index()


def coverage_summary() -> dict:
    con = connect(read_only=True)
    try:
        row = con.execute(
            "SELECT COUNT(DISTINCT ticker), MIN(date), MAX(date), COUNT(*) FROM prices"
        ).fetchone()
        last = con.execute(
            "SELECT run_at, universe, requested, ok, failed, coverage "
            "FROM fetch_log ORDER BY run_at DESC LIMIT 1").fetchone()
    finally:
        con.close()
    out = {
        "n_tickers": row[0] or 0,
        "date_min": str(row[1]) if row[1] else None,
        "date_max": str(row[2]) if row[2] else None,
        "n_rows": row[3] or 0,
        "last_fetch": None,
    }
    if last:
        out["last_fetch"] = {
            "run_at": str(last[0]), "universe": last[1], "requested": last[2],
            "ok": last[3], "failed": last[4], "coverage": round(last[5] or 0, 3),
        }
    return out
