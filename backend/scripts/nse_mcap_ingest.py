"""NSE's official market cap and the ISIN company map -> backend/data/nse_layer.duckdb (adr-050).

NSE's daily price bundle (PR{ddmmyy}.zip) carries MCAP{ddmmyyyy}.csv — issue size x close for every
listed security — from 2024-02-01 (the 31 Jan 2024 bundle has none). From that day the Rs500cr
universe and the `mcap` feature read NSE's own number instead of Trendlyne's pit_mcap (step 3).

The same run rebuilds the company map the engine reads it through:
  ticker_map  every NSE mainboard ticker whose ISIN is an ordinary equity share — INE + security
              code 01, so no ETFs or fund units (INF), partly-paid or DVR lines (IN9) or rights
              entitlements (code 20, e.g. ADANI-RE, which NSE's MCAP file lists in series EQ) ->
              its engine symbol. Tickers sharing an ISIN are one company (renames: ZOMATO ->
              ETERNAL), grouped transitively. A company's engine symbol is the symbol Trendlyne
              knows it by when Trendlyne lists it (stocks / recovered_symbols / universe_membership
              / delistings), else its most recently traded ticker.
  companies   per engine symbol: its first NSE MCAP reading, its highest official market cap,
              whether Trendlyne ever gave it a universe row — and `survivor`, a company NSE put
              above the floor that has none (#959, step 5).

Usage (from backend/):
  .venv/bin/python scripts/nse_mcap_ingest.py --recent 5       nightly, in the EOD window after Bhavcopy
  .venv/bin/python scripts/nse_mcap_ingest.py --backfill       2024-02-01 -> today, skipping days held
  .venv/bin/python scripts/nse_mcap_ingest.py --backfill --download-only   files only, no map
  .venv/bin/python scripts/nse_mcap_ingest.py --map-only

Writes ONLY nse_layer.duckdb. The map opens bhavcopy.duckdb and trendlyne.duckdb READ-ONLY: in the
EOD window the api is stopped; outside it read-only opens coexist with the api's (adr-018). The api
attaches nse_layer.duckdb read-only, so writes to it belong in the EOD window once it is deployed.
Exit code 1 when a fetched day failed or the map left a Trendlyne universe name unplaced.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from windfall.data.surveillance import _HEADERS  # noqa: E402

DATA = Path(os.environ.get("WINDFALL_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
NL = Path(os.environ.get("WINDFALL_NSE_LAYER_DB", DATA / "nse_layer.duckdb"))
TL = Path(os.environ.get("WINDFALL_TRENDLYNE_DB", DATA / "trendlyne.duckdb"))
BC = Path(os.environ.get("WINDFALL_BHAVCOPY_DB", DATA / "bhavcopy.duckdb"))
PR = "https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR{tag}.zip"
FIRST_DAY = dt.date(2024, 2, 1)
FLOOR = 500.0
MAINBOARD = ("EQ", "BE", "BZ")

COMPANIES_DDL = """
CREATE TABLE IF NOT EXISTS companies (
    engine_symbol VARCHAR PRIMARY KEY, isin_group VARCHAR, in_trendlyne BOOLEAN,
    has_membership BOOLEAN, first_mcap_date DATE, first_mcap_cr DOUBLE, max_mcap_cr DOUBLE,
    survivor BOOLEAN, membership_symbol VARCHAR)"""

SCHEMA = COMPANIES_DDL + ";" + """
CREATE TABLE IF NOT EXISTS mcap_daily (
    date DATE NOT NULL, symbol VARCHAR NOT NULL, series VARCHAR NOT NULL,
    face_value DOUBLE, issue_size DOUBLE, close DOUBLE, mcap_cr DOUBLE,
    PRIMARY KEY (date, symbol, series));
CREATE TABLE IF NOT EXISTS mcap_days (
    date DATE PRIMARY KEY, status VARCHAR, n_rows INTEGER, fetched_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS ticker_map (
    ticker VARCHAR PRIMARY KEY, engine_symbol VARCHAR, isin_group VARCHAR, in_trendlyne BOOLEAN);
CREATE TABLE IF NOT EXISTS build_log (
    run_at TIMESTAMP, mode VARCHAR, days_ok INTEGER, days_missing INTEGER, days_failed INTEGER,
    mcap_rows BIGINT, tickers INTEGER, companies INTEGER, survivors INTEGER,
    unmapped_over_floor INTEGER, trendlyne_unplaced INTEGER);
"""


def parse_mcap(content: bytes, day: dt.date) -> pd.DataFrame | None:
    """Mainboard rows of one bundle's MCAP file; None when the bundle carries no MCAP file."""
    z = zipfile.ZipFile(io.BytesIO(content))
    name = next((n for n in z.namelist() if n.lower().startswith("mcap")), None)
    if not name:
        return None
    df = pd.read_csv(io.BytesIO(z.read(name)), skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    col = {c.lower(): c for c in df.columns}

    def pick(*keys):
        for k in keys:
            for lc, c in col.items():
                if lc.startswith(k):
                    return c
        raise KeyError(f"MCAP file {name}: none of {keys} in {list(df.columns)}")

    out = pd.DataFrame({
        "date": day,
        "symbol": df[pick("symbol")].astype(str).str.strip().str.upper(),
        "series": df[pick("series")].astype(str).str.strip().str.upper(),
        "face_value": pd.to_numeric(df[pick("face value", "face")], errors="coerce"),
        "issue_size": pd.to_numeric(df[pick("issue size")], errors="coerce"),
        "close": pd.to_numeric(df[pick("close price", "close")], errors="coerce"),
        "mcap_cr": pd.to_numeric(df[pick("market cap")], errors="coerce") / 1e7,
    })
    out = out[out["series"].isin(MAINBOARD) & (out["mcap_cr"] > 0)]
    return out.drop_duplicates(["date", "symbol", "series"])


def fetch_day(s: requests.Session, day: dt.date) -> tuple[str, pd.DataFrame | None]:
    """('ok', rows) | ('missing', None) for a holiday / no MCAP file | ('failed', None)."""
    try:
        r = s.get(PR.format(tag=day.strftime("%d%m%y")), timeout=60)
    except requests.RequestException:
        return "failed", None
    if r.status_code == 404:
        return "missing", None
    if r.status_code != 200 or r.content[:2] != b"PK":
        return "failed", None
    df = parse_mcap(r.content, day)
    return ("ok", df) if df is not None and not df.empty else ("missing", None)


def download(con, days: list[dt.date], skip: tuple[str, ...]) -> dict:
    """Fetch each weekday in `days` unless its stored status is in `skip`."""
    held = {r[0]: r[1] for r in con.execute("SELECT date, status FROM mcap_days").fetchall()}
    s = requests.Session()
    s.headers.update(_HEADERS)
    n = {"ok": 0, "missing": 0, "failed": 0}
    for day in days:
        if day.weekday() >= 5:
            continue
        if held.get(day) in skip:
            continue
        status, df = fetch_day(s, day)
        time.sleep(0.6)                                 # polite to NSE's archive
        n[status] += 1
        con.execute("BEGIN TRANSACTION")
        try:
            if status == "ok":
                con.execute("DELETE FROM mcap_daily WHERE date = ?", [day])
                con.register("df", df)
                con.execute("INSERT INTO mcap_daily SELECT date, symbol, series, face_value, "
                            "issue_size, close, mcap_cr FROM df")
                con.unregister("df")
            con.execute("INSERT OR REPLACE INTO mcap_days VALUES (?, ?, ?, ?)",
                        [day, status, 0 if df is None else len(df), dt.datetime.now()])
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        if status != "missing":
            print(f"{day} {status} {0 if df is None else len(df)}", flush=True)
    return n


def _groups(pairs: list[tuple[str, str]]) -> dict[str, str]:
    """ticker -> group id: tickers sharing an ISIN, transitively (union-find over ticker/ISIN)."""
    parent: dict[str, str] = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for t, isin in pairs:
        a, b = find("T:" + t), find("I:" + isin)
        if a != b:
            parent[max(a, b)] = min(a, b)
    return {k[2:]: find(k) for k in list(parent) if k.startswith("T:")}


def build_map(con) -> dict:
    con.execute(f"ATTACH '{BC}' AS bc (READ_ONLY)")
    con.execute(f"ATTACH '{TL}' AS tl (READ_ONLY)")
    try:
        rows = con.execute("""
            SELECT upper(regexp_replace(ticker, '\\.NS$', '')) AS t, isin, max(date) AS last_date
            FROM bc.bhavcopy_prices
            WHERE series IN ('EQ', 'BE', 'BZ') AND isin LIKE 'INE%' AND substr(isin, 8, 2) = '01'
            GROUP BY 1, 2""").fetchall()
        # Trendlyne universe names trading on the NSE mainboard since the cutover — each must map,
        # or it would lose its membership from 2024-02-01 (read while bc/tl are attached).
        active_tl = {r[0] for r in con.execute(r"""
            SELECT u.symbol
            FROM (SELECT DISTINCT symbol FROM tl.universe_membership WHERE date >= ?) u
            JOIN (SELECT DISTINCT upper(regexp_replace(ticker, '\.NS$', '')) AS t FROM bc.bhavcopy_prices
                  WHERE date >= ? AND series IN ('EQ', 'BE', 'BZ')) b ON b.t = u.symbol""",
            [FIRST_DAY, FIRST_DAY]).fetchall()}
        last_traded: dict[str, dt.date] = {}
        for t, _isin, d in rows:
            last_traded[t] = max(last_traded.get(t, d), d)
        grp = _groups([(t, isin) for t, isin, _ in rows])
        live = {r[0] for r in con.execute(
            "SELECT upper(nsecode) FROM tl.stocks WHERE nsecode <> '' "
            "UNION SELECT upper(nse_symbol) FROM tl.recovered_symbols WHERE nse_symbol <> ''").fetchall()}
        um_last = {s: d for s, d in con.execute(
            "SELECT symbol, max(date) FROM tl.universe_membership GROUP BY 1").fetchall()}
        dead = {r[0] for r in con.execute("SELECT symbol FROM tl.delistings").fetchall()}
    finally:
        con.execute("DETACH bc")
        con.execute("DETACH tl")

    members: dict[str, list[str]] = {}
    for t, g in grp.items():
        members.setdefault(g, []).append(t)
    tmap, comp_tl = [], {}
    for g, ts in members.items():
        latest = max(ts, key=lambda t: (last_traded.get(t, dt.date.min), t))
        pick = ([t for t in ts if t in live] or
                sorted((t for t in ts if t in um_last), key=lambda t: um_last[t], reverse=True) or
                [t for t in ts if t in dead])
        if pick:
            # Two Trendlyne symbols in one company: keep the one NSE trades now.
            engine = latest if latest in pick else max(pick, key=lambda t: (last_traded.get(t, dt.date.min), t))
            in_tl = True
        else:
            engine, in_tl = latest, False
        # Membership is a COMPANY fact: any of its tickers carrying universe_membership rows counts.
        # universe_membership is frozen with the price history (adr-050) while stocks.nsecode follows
        # every rename, so after a rename the rows sit under the OLD symbol and the engine symbol is
        # the NEW one. Testing only the engine symbol made such a company a "survivor" and counted
        # it twice before the cutover (iter-204 verifier B5); membership_symbol records where its
        # frozen rows live so the engine reads them under the new name.
        with_rows = [t for t in ts if t in um_last]
        msym = (engine if engine in um_last else
                max(with_rows, key=lambda t: um_last[t]) if with_rows else None)
        comp_tl[engine] = (g, in_tl, bool(with_rows), msym)
        tmap += [(t, engine, g, in_tl) for t in ts]

    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("DELETE FROM ticker_map")
        con.executemany("INSERT INTO ticker_map VALUES (?, ?, ?, ?)", tmap)
        con.execute("DROP TABLE IF EXISTS companies")      # recreated: the shape grew in iter-204
        con.execute(COMPANIES_DDL)
        stats = con.execute("""
            SELECT t.engine_symbol, min(m.date) AS d0, arg_min(m.mcap_cr, m.date) AS m0, max(m.mcap_cr) AS mx
            FROM mcap_daily m JOIN ticker_map t ON t.ticker = m.symbol GROUP BY 1""").fetchall()
        comps = []
        for eng, d0, m0, mx in stats:
            g, in_tl, has_m, msym = comp_tl[eng]
            comps.append((eng, g, in_tl, has_m, d0, m0, mx, (not has_m) and mx > FLOOR, msym))
        con.executemany("INSERT INTO companies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", comps)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    unmapped = con.execute("""
        SELECT count(DISTINCT m.symbol) FROM mcap_daily m LEFT JOIN ticker_map t ON t.ticker = m.symbol
        WHERE t.ticker IS NULL AND m.mcap_cr > ?""", [FLOOR]).fetchone()[0]
    # A Trendlyne universe name still trading on the NSE mainboard that no ticker maps to would lose
    # its membership from the cutover. Names that never traded there (BSE-only, SME, REIT/InvIT
    # units) are expected to be absent — the NSE gate excludes them anyway.
    placed = {t for t, _e, _g, _i in tmap}
    unplaced = sorted(s for s in active_tl if s not in placed)
    first_day = con.execute("SELECT min(date) FROM mcap_daily").fetchone()[0]
    surv = [c for c in comps if c[7]]
    n_listed = sum(1 for c in surv if c[4] == first_day)
    return {"tickers": len(tmap), "companies": len(comps), "survivors": len(surv),
            "survivors_listed_at_cutover": n_listed, "unmapped_over_floor": int(unmapped),
            "trendlyne_unplaced": unplaced}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recent", type=int, help="fetch the last N calendar days not yet held")
    ap.add_argument("--backfill", action="store_true", help=f"fetch {FIRST_DAY} -> today, skipping held days")
    ap.add_argument("--download-only", action="store_true")
    ap.add_argument("--map-only", action="store_true")
    a = ap.parse_args()
    con = duckdb.connect(str(NL))
    con.execute(SCHEMA)
    today = dt.date.today()
    n = {"ok": 0, "missing": 0, "failed": 0}
    if not a.map_only:
        if a.backfill:
            days = [FIRST_DAY + dt.timedelta(days=i) for i in range((today - FIRST_DAY).days + 1)]
            n = download(con, days, skip=("ok", "missing"))
        else:
            k = a.recent or 5
            days = [today - dt.timedelta(days=i) for i in range(k - 1, -1, -1)]
            # nightly: a day already held is final; a holiday or a failure is retried
            n = download(con, [d for d in days if d >= FIRST_DAY], skip=("ok",))
        print(f"MCAP days: {n}")
    m = {"tickers": None, "companies": None, "survivors": None, "survivors_listed_at_cutover": None,
         "unmapped_over_floor": None, "trendlyne_unplaced": []}
    if not a.download_only:
        m = build_map(con)
        print(f"map: {m['tickers']} tickers, {m['companies']} companies, {m['survivors']} survivors "
              f"({m['survivors_listed_at_cutover']} already listed on {FIRST_DAY}, the rest listed later), "
              f"{m['unmapped_over_floor']} MCAP symbols over Rs{FLOOR:.0f}cr unmapped, "
              f"Trendlyne universe names unplaced: {m['trendlyne_unplaced']}")
    rows = con.execute("SELECT count(*) FROM mcap_daily").fetchone()[0]
    con.execute("INSERT INTO build_log VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [dt.datetime.now(), "map-only" if a.map_only else ("backfill" if a.backfill else "recent"),
                 n["ok"], n["missing"], n["failed"], rows, m["tickers"], m["companies"], m["survivors"],
                 m["unmapped_over_floor"], len(m["trendlyne_unplaced"])])
    con.close()
    return 1 if n["failed"] or m["trendlyne_unplaced"] else 0


if __name__ == "__main__":
    sys.exit(main())
