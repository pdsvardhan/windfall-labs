"""Ingest NSE daily Bhavcopy into a standalone, survivorship-complete raw price store.

WHY a separate DB: this writes to `data/bhavcopy.duckdb`, NOT the engine's `windfall.duckdb`.
The api container holds a single-writer lock on windfall.duckdb; opening that file from a second
host process would risk the WAL corruption adr-018 ("ONE DOOR") exists to prevent. bhavcopy.duckdb
is untouched by the container, so this long backfill can run while the cockpit stays up.

WHAT it gives: every stock that traded on each day — including names later delisted/merged that
yfinance (current-listings only) can't provide — keyed by ISIN so symbol renames stay linked.
This is the survivorship-bias fix. Prices are RAW (unadjusted); corporate-action adjustment and
wiring into the engine are deliberate later steps.

Two NSE formats, switched by date:
  - UDiFF  (>= 2024-07-08): https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip
  - legacy (<  2024-07-08): https://nsearchives.nseindia.com/content/historical/EQUITIES/YYYY/MON/cmDDMONYYYYbhav.csv.zip

Polite + resumable: skips dates already present, rate-limits, retries with backoff, and treats a
404 (weekend/holiday/not-published) as a no-op.

Usage (run on the server; no need to stop the api — separate DB):
    cd /mnt/storage/websites/windfall-labs/backend && . .venv/bin/activate
    python scripts/bhavcopy_ingest.py 2024-01-01 2024-03-31     # ingest a date range
    python scripts/bhavcopy_ingest.py --recent 400              # last N calendar days
    python scripts/bhavcopy_ingest.py --status                  # coverage report only
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import sys
import time
import zipfile
from pathlib import Path

import duckdb
import pandas as pd
import requests

UDIFF_START = dt.date(2024, 7, 8)               # NSE switched to UDiFF on this date
EQUITY_SERIES = {"EQ", "BE", "BZ", "SM", "ST"}  # tradeable equity series (incl. SME + suspended)
DB = os.environ.get("BHAVCOPY_DB",
                    str(Path(__file__).resolve().parents[1] / "data" / "bhavcopy.duckdb"))
_MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS bhavcopy_prices (
    date DATE NOT NULL, ticker VARCHAR NOT NULL, isin VARCHAR, series VARCHAR,
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, last DOUBLE, prev_close DOUBLE,
    volume DOUBLE, turnover DOUBLE, n_trades DOUBLE,
    PRIMARY KEY (date, ticker)
);
"""


def udiff_url(d: dt.date) -> str:
    return (f"https://nsearchives.nseindia.com/content/cm/"
            f"BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip")


def legacy_url(d: dt.date) -> str:
    return (f"https://nsearchives.nseindia.com/content/historical/EQUITIES/"
            f"{d.year}/{_MON[d.month - 1]}/cm{d.day:02d}{_MON[d.month - 1]}{d.year}bhav.csv.zip")


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def normalize_udiff(df: pd.DataFrame, d: dt.date) -> pd.DataFrame:
    df = df[df["SctySrs"].astype(str).str.strip().isin(EQUITY_SERIES)].copy()
    out = pd.DataFrame({
        "date": d, "ticker": df["TckrSymb"].astype(str).str.strip() + ".NS",
        "isin": df["ISIN"].astype(str).str.strip(), "series": df["SctySrs"].astype(str).str.strip(),
        "open": _num(df["OpnPric"]), "high": _num(df["HghPric"]), "low": _num(df["LwPric"]),
        "close": _num(df["ClsPric"]), "last": _num(df["LastPric"]), "prev_close": _num(df["PrvsClsgPric"]),
        "volume": _num(df["TtlTradgVol"]), "turnover": _num(df["TtlTrfVal"]),
        "n_trades": _num(df["TtlNbOfTxsExctd"]),
    })
    return out.dropna(subset=["close"])


def normalize_legacy(df: pd.DataFrame, d: dt.date) -> pd.DataFrame:
    df = df.rename(columns=lambda c: str(c).strip())
    df = df[df["SERIES"].astype(str).str.strip().isin(EQUITY_SERIES)].copy()
    n_trades = df["TOTALTRADES"] if "TOTALTRADES" in df.columns else pd.Series(pd.NA, index=df.index)
    isin = df["ISIN"] if "ISIN" in df.columns else pd.Series("", index=df.index)
    out = pd.DataFrame({
        "date": d, "ticker": df["SYMBOL"].astype(str).str.strip() + ".NS",
        "isin": isin.astype(str).str.strip(), "series": df["SERIES"].astype(str).str.strip(),
        "open": _num(df["OPEN"]), "high": _num(df["HIGH"]), "low": _num(df["LOW"]),
        "close": _num(df["CLOSE"]), "last": _num(df["LAST"]), "prev_close": _num(df["PREVCLOSE"]),
        "volume": _num(df["TOTTRDQTY"]), "turnover": _num(df["TOTTRDVAL"]),
        "n_trades": _num(n_trades),
    })
    return out.dropna(subset=["close"])


def fetch_day(d: dt.date, session: requests.Session, retries: int = 3) -> pd.DataFrame | None:
    """Return the normalized equity rows for one day, or None for a non-trading day / miss."""
    use_udiff = d >= UDIFF_START
    url = udiff_url(d) if use_udiff else legacy_url(d)
    for attempt in range(retries):
        try:
            r = session.get(url, headers=_HEADERS, timeout=45)
        except requests.RequestException:
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 404:
            return None                       # weekend / holiday / not published
        if r.status_code != 200 or not r.content:
            time.sleep(1.5 * (attempt + 1))
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
                raw = pd.read_csv(z.open(name))
        except (zipfile.BadZipFile, StopIteration, Exception):  # noqa: BLE001
            time.sleep(1.5 * (attempt + 1))
            continue
        return normalize_udiff(raw, d) if use_udiff else normalize_legacy(raw, d)
    return None


def connect():
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(DB)
    con.execute(SCHEMA)
    return con


def ingested_dates(con) -> set:
    return {r[0] for r in con.execute("SELECT DISTINCT date FROM bhavcopy_prices").fetchall()}


def ingest_range(start: dt.date, end: dt.date, delay: float = 0.6) -> dict:
    con = connect()
    have = ingested_dates(con)
    session = requests.Session()
    days = (end - start).days
    ingested = skipped = empty = 0
    rows = 0
    d = start
    while d <= end:
        if d in have or d.weekday() >= 5:     # already done, or Sat/Sun
            skipped += 1
            d += dt.timedelta(days=1)
            continue
        df = fetch_day(d, session)
        if df is None or df.empty:
            empty += 1
        else:
            con.register("incoming", df)
            con.execute("INSERT OR REPLACE INTO bhavcopy_prices SELECT * FROM incoming")
            con.unregister("incoming")
            ingested += 1
            rows += len(df)
            if ingested % 25 == 0:
                print(f"  [{d}] ingested={ingested} rows={rows:,} empty={empty} skipped={skipped}",
                      flush=True)
        time.sleep(delay)
        d += dt.timedelta(days=1)
    cov = status(con)
    con.close()
    return {"requested_days": days + 1, "ingested_days": ingested, "skipped": skipped,
            "non_trading_or_miss": empty, "rows_added": rows, "coverage": cov}


def status(con=None) -> dict:
    own = con is None
    if con is None:
        try:  # read-only so a coverage check doesn't fight a running backfill for the write lock
            con = duckdb.connect(DB, read_only=True)
        except (duckdb.IOException, duckdb.Error):
            return {"status": "busy — bhavcopy.duckdb is locked (a backfill is running); "
                              "watch its log instead"}
    row = con.execute("SELECT COUNT(*), COUNT(DISTINCT ticker), COUNT(DISTINCT date), "
                      "MIN(date), MAX(date) FROM bhavcopy_prices").fetchone()
    out = {"rows": row[0], "tickers": row[1], "trading_days": row[2],
           "from": str(row[3]) if row[3] else None, "to": str(row[4]) if row[4] else None}
    if own:
        con.close()
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="Ingest NSE Bhavcopy into bhavcopy.duckdb")
    p.add_argument("start", nargs="?", help="start date YYYY-MM-DD")
    p.add_argument("end", nargs="?", help="end date YYYY-MM-DD (default: today)")
    p.add_argument("--recent", type=int, help="ingest the last N calendar days")
    p.add_argument("--delay", type=float, default=0.6, help="seconds between requests (politeness)")
    p.add_argument("--status", action="store_true", help="print coverage and exit")
    a = p.parse_args(argv)

    if a.status:
        print(status())
        return
    today = dt.date.today()
    if a.recent:
        start, end = today - dt.timedelta(days=a.recent), today
    elif a.start:
        start = dt.date.fromisoformat(a.start)
        end = dt.date.fromisoformat(a.end) if a.end else today
    else:
        p.error("provide a start date, or --recent N, or --status")
    print(f"Ingesting Bhavcopy {start} .. {end} -> {DB}", flush=True)
    print(ingest_range(start, end, delay=a.delay), flush=True)


if __name__ == "__main__":
    sys.exit(main())
