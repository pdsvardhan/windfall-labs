"""iter-200 (free layer, item 1462): free market cap and the Rs500cr universe vs today's.

SUPERSEDED for the membership comparison (step 4 below): it keys by ticker (renames count as errors),
skips tl.recovered_symbols, and multiplies a split-adjusted close by a same-day (pre-split) share count.
Use explain_membership.py for membership. Steps 1-3 (MCAP download, share-count check, drift) stand.

NSE's daily PR bundle carries `mcapDDMMYYYY.csv` (issue size + market cap per security, official)
from some date in 2023-24 onward. This:
  1. downloads one MCAP file per month-end from its first appearance (polite rate) into the
     research store, plus the latest trading day;
  2. compares NSE's current share counts with today's pit_shares (derived from Trendlyne NP/EPS)
     and NSE's market cap with Trendlyne's own `stocks.mcap` snapshot;
  3. measures share-count drift (issuance/buybacks) between the earliest and latest MCAP files,
     net of splits/bonuses — the error of holding the current share count constant back in time;
  4. rebuilds live-name membership as adjusted_close x NSE issue size (dead names unchanged) and
     compares it with the current universe_membership at every month-end since 2016.

Read-only on trendlyne/bhavcopy; writes only data/free_layer.duckdb.

    .venv/bin/python scripts/free_layer/compare_mcap.py [--skip-download]
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import sys
import time
import zipfile
from pathlib import Path

import duckdb
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from windfall.data.surveillance import _HEADERS  # noqa: E402

DATA = Path(__file__).resolve().parents[2] / "data"
FREE, TL, BC = DATA / "free_layer.duckdb", DATA / "trendlyne.duckdb", DATA / "bhavcopy.duckdb"
PR = "https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR{tag}.zip"
FLOOR = 500.0


def fetch_mcap(s: requests.Session, day: dt.date) -> pd.DataFrame | None:
    r = s.get(PR.format(tag=day.strftime("%d%m%y")), timeout=60)
    time.sleep(1.2)
    if r.status_code != 200 or r.content[:2] != b"PK":
        return None
    z = zipfile.ZipFile(io.BytesIO(r.content))
    name = next((n for n in z.namelist() if n.lower().startswith("mcap")), None)
    if not name:
        return pd.DataFrame()            # bundle exists, but no MCAP file in this era
    df = pd.read_csv(io.BytesIO(z.read(name)), skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns={"Symbol": "symbol", "Series": "series", "Issue Size": "issue_size",
                            "Close Price/Paid up value(Rs.)": "close", "Market Cap(Rs.)": "mcap_rs"})
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df["series"] = df["series"].astype(str).str.strip()
    df = df[df["series"].isin(["EQ", "BE", "BZ", "SM", "ST"])]
    df["date"] = day
    return df[["date", "symbol", "series", "issue_size", "close", "mcap_rs"]]


def month_ends(start: dt.date, end: dt.date) -> list[dt.date]:
    out, d = [], dt.date(start.year, start.month, 1)
    while d <= end:
        nxt = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        out.append(nxt - dt.timedelta(days=1))
        d = nxt
    return out


def download(con) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS nse_mcap (date DATE, symbol VARCHAR, series VARCHAR,
                   issue_size DOUBLE, close DOUBLE, mcap_rs DOUBLE)""")
    have = {r[0] for r in con.execute("SELECT DISTINCT date FROM nse_mcap").fetchall()}
    s = requests.Session()
    s.headers.update(_HEADERS)
    first = None
    for me in month_ends(dt.date(2023, 1, 1), dt.date.today()) + [dt.date.today()]:
        for back in range(7):                          # walk back to the month's last trading day
            day = me - dt.timedelta(days=back)
            if day > dt.date.today() or day.weekday() >= 5:
                continue
            if day in have:
                break
            df = fetch_mcap(s, day)
            if df is None:
                continue
            if df.empty:
                break
            first = first or day
            con.register("df", df)
            con.execute("INSERT INTO nse_mcap SELECT * FROM df")
            con.unregister("df")
            print(f"MCAP {day}: {len(df)} rows")
            break
    print("first month-end with an MCAP file:", first or
          con.execute("SELECT min(date) FROM nse_mcap").fetchone()[0])


def compare(con) -> None:
    con.execute(f"ATTACH '{TL}' AS tl (READ_ONLY)")
    latest = con.execute("SELECT max(date) FROM nse_mcap").fetchone()[0]
    print(f"\n== latest NSE MCAP file {latest} ==")
    cmp = con.execute("""
        WITH n AS (SELECT symbol, arg_max(issue_size, series = 'EQ') issue_size,
                          arg_max(mcap_rs, series = 'EQ') mcap_rs
                   FROM nse_mcap WHERE date = (SELECT max(date) FROM nse_mcap) GROUP BY symbol),
             sym AS (SELECT upper(nsecode) s, pk, mcap FROM tl.stocks WHERE nsecode <> ''),
             ps AS (SELECT pk, arg_max(shares_cr, from_date) shares_cr FROM tl.pit_shares GROUP BY pk)
        SELECT n.symbol, n.issue_size / 1e7 AS nse_shares_cr, ps.shares_cr AS app_shares_cr,
               n.mcap_rs / 1e7 AS nse_mcap_cr, sym.mcap AS tl_mcap_cr
        FROM n JOIN sym ON sym.s = n.symbol LEFT JOIN ps ON ps.pk = sym.pk""").fetchdf()
    a = cmp.dropna(subset=["app_shares_cr"])
    r = (a["app_shares_cr"] / a["nse_shares_cr"])
    print(f"names in both NSE MCAP and pit_shares: {len(a)}")
    print(f"  today's derived share count within 10% of NSE's: {((r - 1).abs() < 0.10).mean():.1%};"
          f" off by >50%: {int(((r - 1).abs() > 0.5).sum())}")
    t = cmp.dropna(subset=["tl_mcap_cr"])
    q = t["nse_mcap_cr"] / t["tl_mcap_cr"]
    print(f"  NSE market cap vs Trendlyne's stocks.mcap snapshot: within 10% for "
          f"{((q - 1).abs() < 0.10).mean():.1%} of {len(t)} (snapshot is from the last harvest, so "
          f"price moves since then are in this too)")
    con.register("cmp", cmp)
    con.execute("CREATE OR REPLACE TABLE check_shares AS SELECT * FROM cmp")

    # share-count drift net of splits/bonuses between the earliest and latest MCAP files
    first = con.execute("SELECT min(date) FROM nse_mcap").fetchone()[0]
    drift = con.execute("""
        WITH f AS (SELECT symbol, arg_max(issue_size, series = 'EQ') i0 FROM nse_mcap
                   WHERE date = (SELECT min(date) FROM nse_mcap) GROUP BY symbol),
             l AS (SELECT symbol, arg_max(issue_size, series = 'EQ') i1 FROM nse_mcap
                   WHERE date = (SELECT max(date) FROM nse_mcap) GROUP BY symbol),
             ca AS (SELECT symbol, exp(sum(ln(ratio))) k FROM ca_events_nse
                    WHERE ratio IS NOT NULL AND ex_date > (SELECT min(date) FROM nse_mcap)
                      AND ex_date <= (SELECT max(date) FROM nse_mcap) GROUP BY symbol)
        SELECT f.symbol, l.i1 / (f.i0 * coalesce(ca.k, 1)) AS net
        FROM f JOIN l USING (symbol) LEFT JOIN ca USING (symbol)""").fetchdf()
    print(f"\n== share-count drift {first} -> {latest}, net of splits/bonuses ({len(drift)} names) ==")
    for lo, hi in [(0, 0.02), (0.02, 0.10), (0.10, 0.5), (0.5, 99)]:
        n = ((drift["net"] - 1).abs().between(lo, hi, inclusive="left")).sum()
        print(f"  |drift| {lo:.0%}-{hi:.0%}: {n}")

    # membership: live names = Trendlyne adjusted close x NSE issue size (latest); dead unchanged
    print("\n== Rs500cr membership: current vs free (live names re-based on NSE share counts) ==")
    rows = []
    for d in pd.date_range("2016-01-31", latest, freq="ME"):
        d = d.date()
        cur = con.execute("""
            SELECT symbol FROM (SELECT symbol, arg_max(mcap_cr, date) m FROM tl.universe_membership
                                WHERE date BETWEEN CAST(? AS DATE) - 14 AND CAST(? AS DATE) GROUP BY symbol)
            WHERE m > ?""", [d, d, FLOOR]).fetchdf()["symbol"]
        free = con.execute("""
            WITH sym AS (SELECT upper(nsecode) s, pk FROM tl.stocks WHERE nsecode <> ''),
                 sh AS (SELECT symbol, issue_size FROM check_shares_nse),
                 px AS (SELECT pk, arg_max(close, date) c FROM tl.ohlcv
                        WHERE date BETWEEN CAST(? AS DATE) - 14 AND CAST(? AS DATE) GROUP BY pk),
                 live AS (SELECT sym.s AS symbol, px.c * sh.issue_size / 1e7 AS m
                          FROM px JOIN sym USING (pk) JOIN sh ON sh.symbol = sym.s),
                 dead AS (SELECT symbol, arg_max(mcap_cr, date) m FROM tl.universe_membership
                          WHERE source = 'dead' AND date BETWEEN CAST(? AS DATE) - 14 AND CAST(? AS DATE)
                          GROUP BY symbol)
            SELECT symbol FROM live WHERE m > ? UNION SELECT symbol FROM dead WHERE m > ?""",
                           [d, d, d, d, FLOOR, FLOOR]).fetchdf()["symbol"]
        c, f = set(cur), set(free)
        rows.append({"date": d, "current": len(c), "free": len(f), "both": len(c & f),
                     "only_current": len(c - f), "only_free": len(f - c)})
    m = pd.DataFrame(rows)
    m["overlap"] = m["both"] / m[["current", "free"]].max(axis=1)
    con.register("m", m)
    con.execute("CREATE OR REPLACE TABLE membership_compare AS SELECT * FROM m")
    for r in m.iloc[::12].itertuples():
        print(f"  {r.date}: current {r.current}, free {r.free}, both {r.both} "
              f"(overlap {r.overlap:.1%}; only-current {r.only_current}, only-free {r.only_free})")
    last = m.iloc[-1]
    print(f"  latest {last.date}: current {last.current}, free {last.free}, overlap {last.overlap:.1%}")
    print(f"  mean overlap 2016->: {m['overlap'].mean():.1%}; min {m['overlap'].min():.1%}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-download", action="store_true")
    a = ap.parse_args()
    con = duckdb.connect(str(FREE))
    try:
        if not a.skip_download:
            download(con)
        con.execute("""CREATE OR REPLACE TABLE check_shares_nse AS
            SELECT symbol, arg_max(issue_size, series = 'EQ') issue_size FROM nse_mcap
            WHERE date = (SELECT max(date) FROM nse_mcap) GROUP BY symbol""")
        compare(con)
    finally:
        con.close()


if __name__ == "__main__":
    main()
