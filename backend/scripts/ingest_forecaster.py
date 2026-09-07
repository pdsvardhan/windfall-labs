#!/usr/bin/env python3
"""Merge a Trendlyne Forecaster harvest (analyst consensus estimates) into trendlyne.duckdb.

INSERT-ONLY, AND THAT IS THE WHOLE POINT. Every other leg in `ingest_refresh.py` replaces at a
key, because those harvests return a series' FULL history and therefore supersede it. This one
does not: `https://trendlyne.com/equity/consensus-estimates/<pk>/x/x/` serves only TODAY's
estimates. There is no history to fetch, and estimates revise.

So the history is the accumulation of snapshots, and a replace — at ANY key — would delete every
prior snapshot on the first run. That is the same silent data loss fixed on 2026-09-07 in 0b0ecce,
which is why the rule is structural here rather than a convention: this script contains no DELETE
and no REPLACE. Rows are anti-joined on the full key and only genuinely new ones are inserted, so
re-running the same day's harvest is idempotent and a new day's harvest adds a layer.

WHY EVERY ROW CARRIES TWO DATES
    period_end  the fiscal period the estimate is FOR   (FY27 -> 2027-03-31)
    as_of       the date we learned it                  (the harvest date)
A backtest asking "what was the consensus FY27 EPS believed to be in Sep 2026?" needs both. One
date cannot answer it, and using period_end alone would silently give a future revision to a past
decision — look-ahead, in the exact form the engine exists to avoid.

COVERAGE — READ THIS BEFORE BUILDING A FACTOR ON THIS TABLE
Full 2026-09-08 harvest, 2,005 stocks probed (base screener PLUS the megacap companion — without
that companion the top ~100 names are silently absent and the numbers below read far worse):
813 stocks (40.5%) have a forward EPS estimate, banded against the Rs500cr universe —
    > Rs50,000cr     186/206   90.3%
    Rs10-50,000cr    296/390   75.9%
    Rs2-10,000cr     281/632   44.5%
    Rs500-2,000cr     50/781    6.4%
Coverage collapses rather than declines, and the bottom band is 39% of the universe. Of the 77
names the eight live paper books held on 2026-09-08, 27 are covered — 36.5% of the 74 that resolve
to a pk, with MOM_roc252_m_10 at 0 of 8 and BLEND_70_30 the outlier at 52.6%. A forward-PE factor
cannot rank a book whose names have no estimates, so this table is research input first; wiring it
into a live strategy would silently shrink that strategy's universe. See adr-047 and to-do #26.

Usage (server, host venv — the api opens this DB read-only, so --apply needs it stopped):
    cd /mnt/storage/websites/windfall-labs/backend
    .venv/bin/python scripts/ingest_forecaster.py data/refresh_staging/forecaster_YYYYMMDD
    docker compose stop api
    .venv/bin/python scripts/ingest_forecaster.py data/refresh_staging/forecaster_YYYYMMDD --apply
    docker compose start api

Input files (from harvesters/trendlyne_harvester_forecaster.js):
    tl_forecaster_estimates_part*.csv   pk,metric,period_end,as_of,value
    tl_forecaster_coverage_part*.csv    pk,as_of,covered,annual_rows,http_status

The coverage file is not bookkeeping. An uncovered stock returns HTTP 200 with an empty estimate
set, so "no rows for this pk" is ambiguous between "no analyst covers it" and "the harvest never
reached it". The coverage ledger resolves that, and it is what the stock-count floor is checked
against — the estimates file alone would look thin for a perfectly good harvest.
"""
import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path

import duckdb

DB = Path(__file__).resolve().parents[1] / "data" / "trendlyne.duckdb"
MIN_STOCKS = 1000  # mirrors the harvester's own truncation guard

DDL_EST = """
CREATE TABLE IF NOT EXISTS forecaster_estimates (
    pk BIGINT, metric VARCHAR, period_end DATE, as_of DATE, value DOUBLE
)"""
DDL_COV = """
CREATE TABLE IF NOT EXISTS forecaster_coverage (
    pk BIGINT, as_of DATE, covered BOOLEAN, annual_rows INTEGER, http_status INTEGER
)"""


def _files(src: Path, stem: str) -> list[Path]:
    return sorted(src.glob(f"tl_{stem}*.csv"))


def _read_union(con, files: list[Path], view: str):
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW {view} AS
        SELECT * FROM read_csv([{','.join(repr(str(f)) for f in files)}],
                               header=true, union_by_name=true)
    """)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="directory holding the staged tl_forecaster_*.csv files")
    ap.add_argument("--apply", action="store_true", help="write (default is a dry-run report)")
    ap.add_argument("--allow-small", action="store_true",
                    help="skip the >=1000-stock floor (a targeted top-up, not a full harvest)")
    args = ap.parse_args()
    src = Path(args.src).expanduser()

    est_f, cov_f = _files(src, "forecaster_estimates"), _files(src, "forecaster_coverage")
    if not est_f:
        sys.exit(f"no tl_forecaster_estimates*.csv in {src}")
    if not cov_f:
        sys.exit(f"no tl_forecaster_coverage*.csv in {src} — the coverage ledger is required, "
                 f"because an uncovered stock and an unreached stock look identical without it")

    if args.apply:
        # No DB yet means a first-ever run and nothing to lose; only an existing one is backed up.
        bak = DB.with_name(f"{DB.name}.pre-forecaster-{dt.date.today()}-bak")
        if DB.exists() and not bak.exists():
            print(f"backing up {DB.name} -> {bak.name} ...")
            shutil.copy2(DB, bak)
        try:
            con = duckdb.connect(str(DB))
        except duckdb.Error as exc:
            sys.exit(f"cannot open read-write ({exc}) — is windfall-api still running? "
                     f"docker compose stop api first.")
        con.execute(DDL_EST)
        con.execute(DDL_COV)
    else:
        # Read-only: the target tables may not exist on a first run, and the anti-joins below need
        # something to join against. Stand in an EMPTY temp table of the same shape — which is also
        # the truthful answer for a first run: nothing is held yet, so every row counts as new.
        con = duckdb.connect(str(DB), read_only=True)
        for tbl, ddl in (("forecaster_estimates", DDL_EST), ("forecaster_coverage", DDL_COV)):
            exists = con.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
                [tbl]).fetchone()[0]
            if not exists:
                print(f"note: {tbl} does not exist yet — --apply will create it")
                con.execute(ddl.replace("CREATE TABLE IF NOT EXISTS",
                                        "CREATE TEMP TABLE IF NOT EXISTS"))

    _read_union(con, est_f, "h_est_raw")
    _read_union(con, cov_f, "h_cov_raw")
    con.execute("""
        CREATE OR REPLACE TEMP VIEW h_est AS
        SELECT DISTINCT CAST(pk AS BIGINT) pk, CAST(metric AS VARCHAR) metric,
               CAST(period_end AS DATE) period_end, CAST(as_of AS DATE) as_of,
               CAST("value" AS DOUBLE) "value"
        FROM h_est_raw
    """)
    con.execute("""
        CREATE OR REPLACE TEMP VIEW h_cov AS
        SELECT DISTINCT CAST(pk AS BIGINT) pk, CAST(as_of AS DATE) as_of,
               CAST(covered AS BOOLEAN) covered, CAST(annual_rows AS INTEGER) annual_rows,
               CAST(http_status AS INTEGER) http_status
        FROM h_cov_raw
    """)

    n_stocks = con.execute("SELECT count(DISTINCT pk) FROM h_cov").fetchone()[0]
    if n_stocks < MIN_STOCKS and not args.allow_small:
        sys.exit(f"coverage ledger holds only {n_stocks} stocks (floor {MIN_STOCKS}). A truncated "
                 f"screener list produces exactly this. Re-run the harvest, or pass --allow-small "
                 f"if this is a deliberate top-up.")

    snaps = [str(r[0]) for r in con.execute(
        "SELECT DISTINCT as_of FROM h_est ORDER BY 1").fetchall()]
    est_in = con.execute("SELECT count(*) FROM h_est").fetchone()[0]
    cov_in = con.execute("SELECT count(*) FROM h_cov").fetchone()[0]
    covered = con.execute("SELECT count(*) FROM h_cov WHERE covered").fetchone()[0]
    fwd = con.execute("""
        SELECT count(DISTINCT pk) FROM h_est
        WHERE metric = 'EPS_AVG' AND period_end > as_of""").fetchone()[0]

    # Anti-join on the FULL key. No DELETE anywhere in this script, by design.
    new_est = con.execute("""
        SELECT count(*) FROM h_est h
        WHERE NOT EXISTS (SELECT 1 FROM forecaster_estimates t
                          WHERE t.pk = h.pk AND t.metric = h.metric
                            AND t.period_end = h.period_end AND t.as_of = h.as_of)
    """).fetchone()[0]
    new_cov = con.execute("""
        SELECT count(*) FROM h_cov h
        WHERE NOT EXISTS (SELECT 1 FROM forecaster_coverage t
                          WHERE t.pk = h.pk AND t.as_of = h.as_of)
    """).fetchone()[0]

    print(f"source            {src}")
    print(f"  files           {[p.name for p in est_f + cov_f]}")
    print(f"  snapshot dates  {', '.join(snaps)}")
    print(f"  stocks probed   {n_stocks}")
    print(f"  covered         {covered}  ({100 * covered / max(n_stocks, 1):.1f}%)")
    print(f"  forward EPS_AVG {fwd} stocks  ({100 * fwd / max(n_stocks, 1):.1f}%)")
    print(f"estimates  rows in file {est_in:>7}   new {new_est:>7}   already held "
          f"{est_in - new_est:>7}")
    print(f"coverage   rows in file {cov_in:>7}   new {new_cov:>7}   already held "
          f"{cov_in - new_cov:>7}")

    if not args.apply:
        held = con.execute("SELECT count(*) FROM forecaster_estimates").fetchone()[0]
        print(f"\nDRY RUN — nothing written. Table currently holds {held} estimate rows.")
        print("Re-run with --apply (api stopped) to ingest.")
        return

    con.execute("BEGIN")
    con.execute("""
        INSERT INTO forecaster_estimates
        SELECT h.pk, h.metric, h.period_end, h.as_of, h."value" FROM h_est h
        WHERE NOT EXISTS (SELECT 1 FROM forecaster_estimates t
                          WHERE t.pk = h.pk AND t.metric = h.metric
                            AND t.period_end = h.period_end AND t.as_of = h.as_of)
    """)
    con.execute("""
        INSERT INTO forecaster_coverage
        SELECT h.pk, h.as_of, h.covered, h.annual_rows, h.http_status FROM h_cov h
        WHERE NOT EXISTS (SELECT 1 FROM forecaster_coverage t
                          WHERE t.pk = h.pk AND t.as_of = h.as_of)
    """)
    con.execute("COMMIT")

    total = con.execute("SELECT count(*) FROM forecaster_estimates").fetchone()[0]
    all_snaps = [str(r[0]) for r in con.execute(
        "SELECT DISTINCT as_of FROM forecaster_estimates ORDER BY 1").fetchall()]
    print(f"\nAPPLIED. forecaster_estimates now holds {total} rows across "
          f"{len(all_snaps)} snapshot(s): {', '.join(all_snaps)}")
    print("docker compose start api")


if __name__ == "__main__":
    main()
