"""Stored-value data audit for windfall.duckdb. Read-only; run with the api stopped.

Reports the things a clean source feed can still hide once it lands in the DB: duplicate
keys, impossible values, real (post-adjustment) price outliers, dead/stale tickers, thin
histories, the exact price<->fundamentals join counts (your true DVM universe), the named
list of fundamentals tickers that failed the price fetch, per-field NULL rates, and the
health of every benchmark/index series.

Run pattern (DuckDB is single-writer — stop the api so this can open the DB):

    docker stop windfall-api
    cd /mnt/storage/websites/windfall-labs/backend && . .venv/bin/activate
    python scripts/data_audit.py
    docker compose up -d --build

Origin: "Windfall Labs - DATA AUDIT (Jun 2026)" review, section 7.
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb

DB = os.environ.get("WINDFALL_DB", str(Path(__file__).resolve().parents[1] / "data" / "windfall.duckdb"))
con = duckdb.connect(DB, read_only=True)


def q(sql, params=None):
    return con.execute(sql, params or []).fetchall()


def one(sql, params=None):
    return con.execute(sql, params or []).fetchone()


print(f"== Windfall data audit :: {DB} ==\n")

# 1) Coverage
n_tk, dmin, dmax, n_rows = one(
    "SELECT COUNT(DISTINCT ticker), MIN(date), MAX(date), COUNT(*) FROM prices")
print(f"[coverage] tickers={n_tk}  rows={n_rows:,}  range={dmin}..{dmax}")

# 2) Duplicates (PK should make this 0)
dups = one("SELECT COUNT(*) FROM (SELECT date,ticker,COUNT(*) c FROM prices GROUP BY 1,2 HAVING c>1)")[0]
print(f"[dupes] duplicate (date,ticker) groups: {dups}  {'OK' if dups == 0 else '*** INVESTIGATE'}")

# 3) Bad values
bad = one("""SELECT
  SUM(CASE WHEN close<=0 OR close IS NULL THEN 1 ELSE 0 END),
  SUM(CASE WHEN volume<0 THEN 1 ELSE 0 END),
  SUM(CASE WHEN adj_close<=0 OR adj_close IS NULL THEN 1 ELSE 0 END),
  SUM(CASE WHEN high<low THEN 1 ELSE 0 END) FROM prices""")
print(f"[values] close<=0:{bad[0]}  volume<0:{bad[1]}  adj<=0:{bad[2]}  high<low:{bad[3]}")

# 4) Adjusted-return outliers (>50% one-day move on adj_close = suspicious after split/bonus removal)
out = q("""WITH r AS (
  SELECT ticker, date, adj_close,
         adj_close/LAG(adj_close) OVER (PARTITION BY ticker ORDER BY date) - 1 AS ret
  FROM prices)
  SELECT ticker, date, ROUND(ret*100,1) FROM r WHERE ABS(ret)>0.5 ORDER BY ABS(ret) DESC LIMIT 25""")
print(f"[outliers] one-day adj moves >50%: {len(out)} shown (top 25):")
for t, d, rp in out[:25]:
    print(f"           {t} {d}  {rp}%")

# 5) Staleness — tickers whose last bar is well before the global max (possible delist/halt/dead symbol)
stale = q("""SELECT ticker, MAX(date) FROM prices GROUP BY ticker
             HAVING MAX(date) < CAST(? AS DATE) - INTERVAL 10 DAY ORDER BY 2 LIMIT 40""", [dmax])
print(f"[stale] tickers with last bar >10d before {dmax}: {len(stale)} (first 40):")
for t, d in stale[:40]:
    print(f"        {t}: last {d}")

# 6) Thin history — tickers with suspiciously few bars (recent listings or broken fetches)
thin = q("SELECT ticker, COUNT(*) c FROM prices GROUP BY ticker HAVING c < 250 ORDER BY c LIMIT 40")
print(f"[thin] tickers with <250 bars (~<1yr): {len(thin)} (first 40):")
for t, c in thin[:40]:
    print(f"       {t}: {c} bars")

# 7) Fundamentals coverage + join to prices
try:
    fn = one("SELECT COUNT(DISTINCT ticker), COUNT(DISTINCT snapshot_date), MAX(snapshot_date) FROM fundamentals")
    print(f"\n[fund] tickers={fn[0]}  snapshots={fn[1]}  latest={fn[2]}")
    both = one("SELECT COUNT(*) FROM (SELECT DISTINCT ticker FROM fundamentals) f "
               "WHERE f.ticker IN (SELECT DISTINCT ticker FROM prices)")[0]
    fund_no_px = q("SELECT ticker FROM (SELECT DISTINCT ticker FROM fundamentals) f "
                   "WHERE f.ticker NOT IN (SELECT DISTINCT ticker FROM prices) ORDER BY 1")
    px_no_fund = one("SELECT COUNT(*) FROM (SELECT DISTINCT ticker FROM prices) p "
                     "WHERE p.ticker NOT IN (SELECT DISTINCT ticker FROM fundamentals)")[0]
    print(f"[fund] have BOTH price+fundamentals: {both}  (this is your real DVM universe)")
    print(f"[fund] fundamentals but NO price ({len(fund_no_px)} — the failed fetches):")
    print("       " + ", ".join(t[0] for t in fund_no_px))
    print(f"[fund] priced but NO fundamentals: {px_no_fund}")
    # per-field NaN rate
    cols = [c[0] for c in con.execute("PRAGMA table_info('fundamentals')").fetchall()
            if c[0] not in ('ticker', 'snapshot_date', 'reporting_date', 'sector')]
    tot = one("SELECT COUNT(*) FROM fundamentals")[0] or 1
    print("[fund] per-field NULL %:")
    for c in cols:
        nn = one(f"SELECT COUNT(*) FROM fundamentals WHERE {c} IS NULL")[0]
        print(f"       {c:18s} {100*nn/tot:5.1f}% null")
except Exception as e:  # noqa: BLE001
    print("[fund] no fundamentals table or error:", e)

# 8) Benchmarks present — detect index series dynamically (NSE index symbols start with '^')
benches = q("SELECT ticker, COUNT(*) c FROM prices WHERE ticker LIKE '^%' GROUP BY ticker ORDER BY ticker")
if benches:
    print("[bench] index/benchmark series found:")
    for b, n in benches:
        print(f"        {b}: {n} rows {'OK' if n > 2000 else '*** MISSING/THIN'}")
else:
    print("[bench] *** no '^'-prefixed index series found in prices")

con.close()
print("\n== done ==")
