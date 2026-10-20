"""iter-200 (free layer, item 1460): backfill NSE corporate actions 2010 -> today into the research store
and validate them against the app's confirmed CA events and Trendlyne's own adjustment steps.

Writes ONLY data/free_layer.duckdb (a standalone research store, never opened by the api). Reads
trendlyne.duckdb / bhavcopy.duckdb read-only. No production code path reads anything written here.

    .venv/bin/python scripts/free_layer/backfill_ca.py [--refetch]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from windfall.data.corp_actions import LANDING, API, parse  # noqa: E402
from windfall.data.surveillance import _HEADERS  # noqa: E402

DATA = Path(__file__).resolve().parents[2] / "data"
FREE = DATA / "free_layer.duckdb"
TL = DATA / "trendlyne.duckdb"
BC = DATA / "bhavcopy.duckdb"


def fetch_year(s: requests.Session, year: int) -> list[dict]:
    end = min(dt.date(year, 12, 31), dt.date.today() + dt.timedelta(days=60))
    r = s.get(API, params={"index": "equities", "from_date": f"01-01-{year}",
                           "to_date": end.strftime("%d-%m-%Y")}, timeout=120)
    r.raise_for_status()
    out = []
    for x in r.json():
        subject = (x.get("subject") or "").strip()
        kind, ratio = parse(subject)
        if kind is None and "rights" in subject.lower():
            kind = "rights"          # ratio + issue price kept in the subject; adjusted by TERP later
        if kind is None:
            continue
        try:
            exd = dt.datetime.strptime(str(x.get("exDate")).strip(), "%d-%b-%Y").date()
        except ValueError:
            continue
        try:
            fv = float(str(x.get("faceVal") or "").strip())
        except ValueError:
            fv = None
        out.append({"symbol": str(x.get("symbol", "")).strip().upper(), "ex_date": exd,
                    "subject": subject, "kind": kind, "ratio": ratio, "face_value": fv,
                    "isin": x.get("isin"), "series": x.get("series")})
    return out


def backfill(con, refetch: bool) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS nse_ca (symbol VARCHAR, ex_date DATE, subject VARCHAR,
                   kind VARCHAR, ratio DOUBLE, face_value DOUBLE, isin VARCHAR, series VARCHAR,
                   fetched_year INTEGER)""")
    have = {r[0] for r in con.execute("SELECT DISTINCT fetched_year FROM nse_ca").fetchall()}
    s = requests.Session()
    s.headers.update(_HEADERS)
    s.headers["Referer"] = LANDING
    s.get(LANDING, timeout=30)
    for year in range(2010, dt.date.today().year + 1):
        if year in have and not refetch and year < dt.date.today().year:
            continue
        rows = fetch_year(s, year)
        con.execute("DELETE FROM nse_ca WHERE fetched_year = ?", [year])
        if rows:
            df = pd.DataFrame(rows)
            df["fetched_year"] = year
            con.register("df", df)
            con.execute("INSERT INTO nse_ca SELECT symbol, ex_date, subject, kind, ratio, face_value, "
                        "isin, series, fetched_year FROM df")
            con.unregister("df")
        print(f"{year}: {len(rows)} split/bonus/consolidation/demerger/scheme rows")
        time.sleep(1.5)
    # One row per (symbol, ex_date). NSE repeats an event under revised subjects ("Bonus 1:10
    # (Record Date Revised)"), so distinct (kind, ratio) pairs first; then a split AND a bonus on the
    # same ex-date (TITAN 2011: 10:1 split + 1:1 bonus = 20) multiply — the price step is their product.
    con.execute("""CREATE OR REPLACE TABLE ca_events_nse AS
        WITH d AS (SELECT DISTINCT symbol, ex_date, kind, ratio FROM nse_ca WHERE kind <> 'rights')
        SELECT symbol, ex_date,
               string_agg(kind, '+' ORDER BY kind) AS kind,
               CASE WHEN count(ratio) = 0 THEN NULL ELSE exp(sum(ln(ratio))) END AS ratio,
               count(*) AS n_events
        FROM d GROUP BY symbol, ex_date""")


def validate(con) -> None:
    con.execute(f"ATTACH '{TL}' AS tl (READ_ONLY)")
    con.execute(f"ATTACH '{BC}' AS bc (READ_ONLY)")
    print("\n== NSE list ==")
    print(con.execute("""SELECT kind, count(*), count(ratio), min(ex_date), max(ex_date)
                         FROM ca_events_nse GROUP BY kind ORDER BY 2 DESC""").fetchall())
    unparsed = con.execute("""SELECT symbol, ex_date, subject FROM nse_ca
                              WHERE kind IN ('split','bonus','consolidation') AND ratio IS NULL""").fetchall()
    print(f"split/bonus/consolidation with no parsed ratio: {len(unparsed)}", unparsed[:8])

    # 1. vs the app's 450 share-step-confirmed events (ca_events, built from Bhavcopy gaps)
    print("\n== vs ca_events (app-derived, share-step confirmed) ==")
    m = con.execute("""
        WITH a AS (SELECT ticker, ex_date, ca_ratio FROM tl.ca_events),
             n AS (SELECT symbol, ex_date, ratio FROM ca_events_nse WHERE ratio IS NOT NULL)
        SELECT count(*) AS app_events,
               count(*) FILTER (WHERE EXISTS (SELECT 1 FROM n WHERE n.symbol=a.ticker
                     AND abs(datediff('day', n.ex_date, a.ex_date)) <= 3
                     AND abs(n.ratio / a.ca_ratio - 1) < 0.08)) AS matched_ratio,
               count(*) FILTER (WHERE EXISTS (SELECT 1 FROM n WHERE n.symbol=a.ticker
                     AND abs(datediff('day', n.ex_date, a.ex_date)) <= 3)) AS matched_date
        FROM a""").fetchall()
    print("app events / NSE match (date+ratio) / NSE match (date only):", m)
    miss = con.execute("""
        SELECT a.ticker, a.ex_date, a.ca_ratio FROM tl.ca_events a
        WHERE NOT EXISTS (SELECT 1 FROM ca_events_nse n WHERE n.symbol=a.ticker
                          AND abs(datediff('day', n.ex_date, a.ex_date)) <= 3)
        ORDER BY a.ex_date LIMIT 25""").fetchall()
    print("app events NSE does not list (first 25):", miss)

    # 2. vs Trendlyne's own adjustment: for live names, factor = tl_close / raw_close steps at each
    #    split/bonus ex-date by 1/ratio. Measure the step Trendlyne actually took at each NSE event.
    print("\n== vs Trendlyne's adjusted ohlcv (live names, events inside Trendlyne history) ==")
    steps = con.execute(r"""
        WITH sym AS (SELECT upper(nsecode) s, pk FROM tl.stocks WHERE nsecode <> ''
                     UNION SELECT upper(nse_symbol), pk FROM tl.recovered_symbols WHERE nse_symbol <> ''),
             last AS (SELECT pk, max(date) last_tl FROM tl.ohlcv GROUP BY pk),
             ev AS (SELECT n.symbol, n.ex_date, n.ratio, sym.pk FROM ca_events_nse n
                    JOIN sym ON sym.s = n.symbol JOIN last USING (pk)
                    WHERE n.ratio IS NOT NULL AND n.ex_date <= last.last_tl
                      AND n.ex_date >= DATE '2010-01-15'),
             f AS (SELECT ev.symbol, ev.ex_date, ev.ratio, y.date, y.close / b.close AS fac
                   FROM ev JOIN tl.ohlcv y ON y.pk = ev.pk
                    AND y.date BETWEEN ev.ex_date - 10 AND ev.ex_date + 10
                   JOIN bc.bhavcopy_prices b
                     ON upper(regexp_replace(b.ticker, '\.NS$', '')) = ev.symbol AND b.date = y.date
                   WHERE b.close > 0 AND b.series IN ('EQ', 'BE'))
        SELECT symbol, ex_date, ratio,
               arg_max(fac, date) FILTER (WHERE date < ex_date) AS fac_before,
               arg_min(fac, date) FILTER (WHERE date >= ex_date) AS fac_after
        FROM f GROUP BY symbol, ex_date, ratio""").fetchdf()
    steps["tl_step"] = steps["fac_after"] / steps["fac_before"]
    steps["ok"] = (steps["tl_step"] / steps["ratio"] - 1).abs() < 0.03
    print(f"NSE ratio events inside Trendlyne history with prices on both sides: {len(steps.dropna())}")
    print(f"  Trendlyne took the same step: {int(steps['ok'].sum())} "
          f"({steps['ok'].mean():.1%} of measurable)")
    bad = steps.dropna()[~steps.dropna()["ok"]].sort_values("ex_date")
    print("  disagreements (first 25):")
    for r in bad.head(25).itertuples():
        print(f"   {r.symbol:12s} {r.ex_date} NSE ratio {r.ratio:.3f}  Trendlyne step {r.tl_step:.3f}")
    con.register("steps", steps)
    con.execute("CREATE OR REPLACE TABLE check_tl_steps AS SELECT * FROM steps")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refetch", action="store_true")
    a = ap.parse_args()
    con = duckdb.connect(str(FREE))
    try:
        backfill(con, a.refetch)
        validate(con)
    finally:
        con.close()


if __name__ == "__main__":
    main()
