#!/usr/bin/env python3
"""
Phase 0 loader: build trendlyne.duckdb from the trendlyne_data/ CSV folder.

Each folder -> its own narrow table (long format), joined on `pk`.
This DB is STANDALONE (its own file, single writer here, opened READ-ONLY by the
engine) so it never opens windfall.duckdb -- ONE DOOR / adr-018 safe.

Run on the server:
    backend/.venv/bin/python load_trendlyne.py
"""
import duckdb, os, sys, time

DATA = "/mnt/storage/websites/windfall-labs/backend/data/trendlyne_data"
DB   = "/mnt/storage/websites/windfall-labs/backend/data/trendlyne.duckdb"

# folder/glob -> table name. Every long table is pk,<score|metric>,date,value.
TABLES = {
    # long-format history tables
    "dvm_history":          "dvm_scores/*.csv",
    "valuation_ratios":     "valuation_ratios/*.csv",
    "pnl_quarterly":        "pnl_quarterly/*.csv",
    "growth_quality":       "growth_quality/*.csv",
    "ownership":            "ownership/*.csv",
    "pnl_annual":           "pnl_annual/*.csv",
    "balance_sheet":        "balance_sheet/*.csv",
    "cashflow":             "cashflow/*.csv",
    "ratios_annual":        "ratios_annual/*.csv",
    "financials_other":     "financials_other/*.csv",
    # special-schema tables
    "corporate_actions":    "corporate_actions/*.csv",
    "result_dates":         "result_dates/*.csv",
    "shareholding_summary": "shareholding_summary/*.csv",
    # reference / lookup
    "stocks":               "_reference/tl_stocks.csv",
    "sector_map":           "_reference/tl_sector_map.csv",
    "recovered_symbols":    "_reference/tl_recovered_symbols.csv",
    "annual_metadata":      "tl_annual_metadata.csv",
}


def main():
    if not os.path.isdir(DATA):
        print(f"ERROR: data dir not found: {DATA}")
        sys.exit(1)
    if os.path.exists(DB):
        print(f"ERROR: {DB} already exists -- refusing to overwrite. "
              f"Delete it first for a clean rebuild.")
        sys.exit(1)

    con = duckdb.connect(DB)
    t0 = time.time()
    # Full-scan auto-detect (sample_size=-1) so types are inferred from ALL rows,
    # not a 20k sample; default ignore_errors=false so any malformed row FAILS loud.
    for table, glob in TABLES.items():
        path = os.path.join(DATA, glob)
        con.execute(
            f"CREATE TABLE {table} AS "
            f"SELECT * FROM read_csv('{path}', header=true, auto_detect=true, sample_size=-1, "
            f"strict_mode=false)"  # megacap merge mixes quoted/unquoted names -> not strict RFC-4180
        )
        print(f"  loaded  {table}")

    # Light join/lookup indexes only (DuckDB scans columnar fast; skip on huge long tables)
    con.execute("CREATE INDEX idx_stocks_pk ON stocks(pk)")
    con.execute("CREATE INDEX idx_sector_pk ON sector_map(pk)")

    # Verification summary (counts + inferred column types) before closing.
    print("\n=== SUMMARY ===")
    grand = 0
    for (t,) in con.execute("SHOW TABLES").fetchall():
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        grand += n
        info = con.execute(f"PRAGMA table_info('{t}')").fetchall()
        coltypes = " ".join(f"{c[1]}:{c[2]}" for c in info)
        print(f"  {t:22s} {n:>11,}  [{coltypes}]")
    print(f"\n  TOTAL ROWS: {grand:,}")
    con.close()
    print(f"Built {DB} in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
