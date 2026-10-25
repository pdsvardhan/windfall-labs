"""iter-206 (#970): the symbol list the NSE filings fetch works through.

Every company that was ever in the point-in-time Rs500cr universe since Jan 2018 (the earliest NSE
XBRL), with the other tickers it has used (same ISIN, newest first) in `alts` — NSE answers by the
CURRENT symbol, so a renamed company (ZOMATO -> ETERNAL) is found through its alias.

Read-only. Run with WINDFALL_DATA_DIR = live data dir and WINDFALL_DB = a COPY of windfall.duckdb.
Usage: python -I nse_symbols.py <out.csv> [from_date]
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from windfall.data import trendlyne_store as ts  # noqa: E402

out = Path(sys.argv[1])
start = sys.argv[2] if len(sys.argv) > 2 else "2018-01-31"
months = pd.date_range(start, "2026-10-31", freq="ME")
names = sorted(set().union(*[ts.pit_universe(d.date()) for d in months]))
aliases = ts._ticker_aliases()
last = dict(ts._con().execute(
    "SELECT upper(regexp_replace(ticker,'\\.NS$','')), max(date) FROM bc.bhavcopy_prices "
    "WHERE series='EQ' GROUP BY 1").fetchall())
sector = ts.sector_map()
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["symbol", "alts", "sector"])
    for s in names:
        s = s.replace(".NS", "")
        alts = sorted((a for a in aliases.get(s, ()) if a != s), key=lambda a: last.get(a) or pd.Timestamp(0).date(),
                      reverse=True)
        w.writerow([s, ";".join(alts), sector.get(s) or ""])
print(f"{len(names)} symbols since {start}; with aliases {sum(1 for s in names if len(aliases.get(s, ())) > 1)}")
