"""iter-23 one-shot data fixes (#84 audit-F4 + #88 audit-F11/F12). Run with the api STOPPED.

F4  — 5 renamed-but-marked-dead names get rename_map rows so pre-rename history attaches to the
      live successor in future screener/history backfills (#89/#92/#93 consume this registry).
      They stay in `delistings`: the old symbol genuinely stopped trading, and the engine selling
      at the rename boundary is an acceptable exit (audit F4). What was missing is the LINK.
F11 — clamp the ~67 OHLC float-rounding rows (high<low or high/low inconsistent vs open/close,
      magnitude ~0.001, almost all pk 2284) to high=greatest(o,h,l,c), low=least(o,h,l,c).
F12 — index_ohlcv open/high/low/volume are VARCHAR (close/last DOUBLE); cast to DOUBLE so the
      latent hazard (any future reader parsing strings) is gone.

Idempotent: re-running skips rename rows that exist and finds zero clamp rows the second time.
"""
import sys

import duckdb

TL = "/mnt/storage/websites/windfall-labs/backend/data/trendlyne.duckdb"
BC = "/mnt/storage/websites/windfall-labs/backend/data/bhavcopy.duckdb"

# audit F4: old dead symbol -> live successor (rename/merger chains, researched 2026-06-24)
RENAMES = {
    "SRTRANSFIN": "SHRIRAMFIN",   # Shriram Transport Finance -> Shriram Finance (merger 2022-11)
    "NIITTECH": "COFORGE",        # NIIT Technologies -> Coforge (2020-08)
    "PANTALOONR": "FRETAIL",      # Pantaloon Retail -> Future Retail (2013; successor itself dead)
    "IIFLWAM": "360ONE",          # IIFL Wealth -> 360 ONE WAM (2023)
    "TATAMTRDVR": "TATAMOTORS",   # DVR cancelled into Tata Motors ordinary (2024 scheme)
}

con = duckdb.connect(TL)
con.execute(f"ATTACH '{BC}' AS bc (READ_ONLY)")
q = lambda s, *p: con.execute(s, p).fetchall()

con.execute("""CREATE TEMP VIEW tl_syms AS
  SELECT upper(nsecode) sym FROM stocks WHERE nsecode IS NOT NULL AND nsecode<>''
  UNION SELECT upper(nse_symbol) FROM recovered_symbols
  WHERE nse_symbol IS NOT NULL AND nse_symbol<>''""")

failed = []

print("== F4: rename_map reconciliation ==")
for old, new in RENAMES.items():
    if q("SELECT 1 FROM rename_map WHERE upper(old_sym)=?", old):
        print(f"  {old}: already in rename_map — skipped")
        continue
    # ISIN: prefer bhavcopy (authoritative), fall back to the delistings registry, else NULL.
    isin_rows = q("""SELECT isin, max(date) FROM bc.bhavcopy_prices
                     WHERE upper(regexp_replace(ticker,'\\.NS$','')) = ? AND isin IS NOT NULL
                     GROUP BY isin ORDER BY 2 DESC LIMIT 1""", old)
    isin = isin_rows[0][0] if isin_rows else None
    if isin is None:
        d = q("SELECT isin FROM delistings WHERE upper(symbol)=? AND isin IS NOT NULL LIMIT 1", old) \
            if q("""SELECT 1 FROM information_schema.columns
                    WHERE table_name='delistings' AND column_name='isin'""") else []
        isin = d[0][0] if d else None
    live_in_tl = bool(q("SELECT 1 FROM tl_syms WHERE sym=?", new))
    con.execute("INSERT INTO rename_map (old_sym, isin, live_sym, live_in_tl) VALUES (?,?,?,?)",
                [old, isin, new, live_in_tl])
    print(f"  {old} -> {new}  isin={isin or 'NULL'}  live_in_tl={live_in_tl}")

print("== F11: OHLC clamp ==")
bad = q("""SELECT count(*) FROM ohlcv
           WHERE high < low OR high < greatest(open, close) OR low > least(open, close)""")[0][0]
print(f"  inconsistent rows before: {bad}")
if bad:
    worst = q("""SELECT max(greatest(greatest(open,close)-high, low-least(open,close), low-high))
                 FROM ohlcv
                 WHERE high < low OR high < greatest(open, close) OR low > least(open, close)""")[0][0]
    if worst is not None and worst > 1.0:
        # The audit measured ~0.001 rounding; anything larger is NOT the known cosmetic defect.
        print(f"  ABORT: worst inconsistency magnitude {worst} > 1.0 rupee — this is not the "
              f"float-rounding cosmetic case the audit cleared for clamping. Investigate first.")
        sys.exit(1)
    con.execute("""UPDATE ohlcv
                   SET high = greatest(open, high, low, close),
                       low  = least(open, high, low, close)
                   WHERE high < low OR high < greatest(open, close) OR low > least(open, close)""")
after = q("""SELECT count(*) FROM ohlcv
             WHERE high < low OR high < greatest(open, close) OR low > least(open, close)""")[0][0]
print(f"  inconsistent rows after: {after}")

print("== F12: index_ohlcv VARCHAR -> DOUBLE ==")
cols = {r[0]: r[1] for r in q("""SELECT column_name, data_type FROM information_schema.columns
                                 WHERE table_name='index_ohlcv'""")}
for c in ("open", "high", "low", "volume"):
    if cols.get(c, "").upper() == "VARCHAR":
        n_bad = q(f"""SELECT count(*) FROM index_ohlcv
                      WHERE {c} IS NOT NULL AND {c} <> '' AND TRY_CAST({c} AS DOUBLE) IS NULL""")[0][0]
        if n_bad:
            print(f"  {c}: {n_bad} non-castable values would become NULL — listing 5:")
            for r in q(f"""SELECT DISTINCT {c} FROM index_ohlcv
                           WHERE {c} IS NOT NULL AND {c} <> '' AND TRY_CAST({c} AS DOUBLE) IS NULL
                           LIMIT 5"""):
                print(f"    {r[0]!r}")
        con.execute(f"ALTER TABLE index_ohlcv ALTER {c} SET DATA TYPE DOUBLE "
                    f"USING TRY_CAST({c} AS DOUBLE)")
        print(f"  {c}: VARCHAR -> DOUBLE ({n_bad} value(s) nulled)")
    else:
        print(f"  {c}: already {cols.get(c)} — skipped")

print("== verify ==")
print("  rename_map rows:", q("SELECT count(*) FROM rename_map")[0][0])
for r in q("SELECT old_sym, live_sym, live_in_tl FROM rename_map WHERE old_sym IN "
           "('SRTRANSFIN','NIITTECH','PANTALOONR','IIFLWAM','TATAMTRDVR') ORDER BY old_sym"):
    print("   ", r)
print("  index_ohlcv types:",
      {r[0]: r[1] for r in q("""SELECT column_name, data_type FROM information_schema.columns
                                WHERE table_name='index_ohlcv'
                                AND column_name IN ('open','high','low','close','volume')""")})
con.close()
print("DONE" if not failed else f"FAILED lookups: {failed}")
sys.exit(0 if not failed else 1)
