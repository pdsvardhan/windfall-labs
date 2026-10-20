"""iter-200 (item 1463 input): how many paper buys were in names NSE's official market cap put BELOW
Rs500cr at the time — i.e. names only the current share-count method let into the universe.

Uses the current paper record via the API and NSE's official MCAP files (free_layer.duckdb).
Read-only.
"""
import json
import urllib.request
from pathlib import Path

import duckdb
import pandas as pd

DATA = Path(__file__).resolve().parents[2] / "data"
with urllib.request.urlopen("http://127.0.0.1:8505/api/paper/positions", timeout=120) as r:
    pos = pd.DataFrame(json.load(r))
pos = pos[pos["status"].isin(["open", "closed"]) & pos["entry_date"].notna()].copy()
pos["entry_date"] = pd.to_datetime(pos["entry_date"])

con = duckdb.connect(str(DATA / "free_layer.duckdb"), read_only=True)
mc = con.execute("""SELECT date, symbol, max(mcap_rs) / 1e7 AS mcap_cr FROM nse_mcap
                    WHERE series IN ('EQ', 'BE') GROUP BY date, symbol""").fetchdf()
mc["date"] = pd.to_datetime(mc["date"])
dates = sorted(mc["date"].unique())

rows = []
for p in pos.itertuples():
    prior = [d for d in dates if d <= p.entry_date]          # last official reading before the buy
    if not prior:
        continue
    d = prior[-1]
    hit = mc[(mc["date"] == d) & (mc["symbol"] == p.ticker.upper())]
    off = float(hit["mcap_cr"].iloc[0]) if len(hit) else None
    rows.append({"book": p.strategy_id, "ticker": p.ticker, "entry": p.entry_date.date(),
                 "official_mcap_cr": off, "below": off is not None and off <= 500})
df = pd.DataFrame(rows)
print(f"paper buys checked against the prior official month-end: {len(df)}")
print(f"  bought while NSE's official mcap was <= Rs500cr: {int(df['below'].sum())}")
print(f"  no official reading (not in that month's file): {int(df['official_mcap_cr'].isna().sum())}")
print(df[df["below"]].sort_values(["book", "entry"]).to_string(index=False))
