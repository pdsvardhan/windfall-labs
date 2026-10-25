"""iter-206 (#969): list the point-in-time universe names that the screener.in store does not hold.

Names ever in the Rs500cr universe 2016-26 that have no row in fundamentals_history, split into
banks/NBFCs (by Trendlyne's sector label — the store excludes financials by design) and the rest.
Writes <out>/missing_nonbank.csv (symbol,name,sector) for the fetch and prints the counts.

Read-only. Run with WINDFALL_DATA_DIR = live data dir and WINDFALL_DB = a COPY of windfall.duckdb.
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from windfall.data import trendlyne_store as ts  # noqa: E402

DATA = Path(os.environ["WINDFALL_DATA_DIR"])
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

months = pd.date_range("2016-07-31", "2026-08-31", freq="ME")
names = sorted(set().union(*[ts.pit_universe(d.date()) for d in months]))
store = duckdb.connect(str(DATA / "screener_fundamentals.duckdb"), read_only=True)
held = {r[0].replace(".NS", "") for r in store.execute(
    "SELECT DISTINCT ticker FROM fundamentals_history").fetchall()}
quarantined = {r[0] for r in store.execute(
    "SELECT symbol FROM slug_map").fetchall()} if "slug_map" in {
    r[0] for r in store.execute("SHOW TABLES").fetchall()} else set()
sector = ts.sector_map()
dead = {r[0] for r in ts._con().execute("SELECT symbol FROM delistings").fetchall()}


def is_fin(s):
    v = (sector.get(s) or "").lower()
    return "bank" in v or "financ" in v


missing = [s for s in names if s.replace(".NS", "") not in held]
fin = [s for s in missing if is_fin(s)]
non = [s for s in missing if not is_fin(s)]
print(f"ever in universe {len(names)}; in store {len(names) - len(missing)}; missing {len(missing)} "
      f"(banks/NBFCs {len(fin)}, non-bank {len(non)}, of which delisted {len([s for s in non if s in dead])}, "
      f"already slug-mapped {len([s for s in non if s in quarantined])})")
with open(OUT / "missing_nonbank.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["symbol", "name", "sector"])
    for s in non:
        w.writerow([s.replace(".NS", ""), "", sector.get(s) or ""])
