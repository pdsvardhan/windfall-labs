"""NSE daily index-close ingest for Windfall Labs (audit #85).

The Trendlyne bulk harvest is a manual, WAF-gated in-browser pull, so `index_ohlcv` goes stale between
pulls — and stale index data blinds the live-signal REGIME overlay (index vs its MA) and the backtest
benchmark. NSE publishes a daily index-close file that IS fetchable server-side (no WAF):

    https://archives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv

This script splices those daily rows onto `index_ohlcv` for the indices we track, so the regime overlay
and benchmark stay current without a manual harvest. It maps CSV index names -> the store's own pk via
`index_map`, is idempotent (delete-then-insert per pk+date), and skips non-trading days (HTTP 404).

adr-018-safe: the api attaches trendlyne.duckdb READ-ONLY, so a host writer conflicts on the lock. Run
this with the api stopped (the wrapper cron does `docker compose stop api` -> ingest -> start api), the
same exclusive-write pattern the nightly Bhavcopy ingest uses.

Usage:
    python scripts/index_ingest.py --recent 20          # last 20 calendar days up to today
    python scripts/index_ingest.py --from 2026-06-13 --to 2026-07-15
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import sys
import urllib.request

import duckdb
import pandas as pd

DB = os.environ.get("WINDFALL_TRENDLYNE_DB",
                    os.path.join(os.environ.get("WINDFALL_DATA_DIR", "data"), "trendlyne.duckdb"))
URL = "https://archives.nseindia.com/content/indices/ind_close_all_{ddmmyyyy}.csv"
UA = "Mozilla/5.0 (Windfall-Labs index ingest)"

# CSV "Index Name" -> the name stored in index_map (usually identical). Extend if NSE renames one.
_CSV_TO_MAP = {
    "Nifty 50": "Nifty 50", "Nifty Next 50": "Nifty Next 50", "Nifty 500": "Nifty 500",
    "Nifty Midcap 150": "Nifty Midcap 150", "Nifty Smallcap 250": "Nifty Smallcap 250",
}


def _name_to_pk(con) -> dict[str, int]:
    rows = con.execute("SELECT name, pk FROM index_map").fetchall()
    return {n: pk for n, pk in rows}


def _fetch_day(d: dt.date) -> pd.DataFrame | None:
    url = URL.format(ddmmyyyy=d.strftime("%d%m%Y"))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                return None
            raw = resp.read()
    except Exception:
        return None
    try:
        df = pd.read_csv(io.BytesIO(raw))
    except Exception:
        return None
    if "Index Name" not in df.columns or "Closing Index Value" not in df.columns:
        return None
    return df


def _num(x) -> float | None:
    try:
        v = float(str(x).replace(",", "").strip())
        return v
    except Exception:
        return None


def ingest(start: dt.date, end: dt.date) -> dict:
    con = duckdb.connect(DB)   # read-write; caller must have stopped the api (lock)
    name_pk = _name_to_pk(con)
    want = {csv: name_pk[mapname] for csv, mapname in _CSV_TO_MAP.items() if mapname in name_pk}
    if not want:
        con.close()
        raise SystemExit("index_map has none of the tracked index names — aborting.")
    days = trading = inserted = 0
    d = start
    while d <= end:
        if d.weekday() < 5:  # Mon-Fri only (skips most 404s cheaply)
            days += 1
            df = _fetch_day(d)
            if df is not None:
                trading += 1
                rows = []
                for _, r in df.iterrows():
                    nm = str(r["Index Name"]).strip()
                    if nm not in want:
                        continue
                    close = _num(r["Closing Index Value"])
                    if close is None or close <= 0:
                        continue
                    rows.append((int(want[nm]), d,
                                 str(r.get("Open Index Value", "")), str(r.get("High Index Value", "")),
                                 str(r.get("Low Index Value", "")), close, close,
                                 str(r.get("Volume", ""))))
                for row in rows:
                    con.execute("DELETE FROM index_ohlcv WHERE pk=? AND date=?", [row[0], row[1]])
                    con.execute(
                        "INSERT INTO index_ohlcv (pk,date,open,high,low,close,last,volume) "
                        "VALUES (?,?,?,?,?,?,?,?)", list(row))
                    inserted += 1
        d += dt.timedelta(days=1)
    mx = con.execute("SELECT max(date) FROM index_ohlcv WHERE pk=?", [next(iter(want.values()))]).fetchone()[0]
    con.close()
    return {"weekdays_scanned": days, "trading_days": trading, "rows_upserted": inserted,
            "new_max_date": str(mx), "indices": sorted(want.keys())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm")
    ap.add_argument("--to", dest="to")
    ap.add_argument("--recent", type=int, help="ingest the last N calendar days up to today")
    a = ap.parse_args()
    today = dt.date.today()
    if a.recent:
        start, end = today - dt.timedelta(days=a.recent), today
    elif a.frm:
        start = dt.date.fromisoformat(a.frm)
        end = dt.date.fromisoformat(a.to) if a.to else today
    else:
        start, end = today - dt.timedelta(days=7), today
    res = ingest(start, end)
    print(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
