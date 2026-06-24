"""One-time migration for audit fixes F5 + F3 registry (2026-06-24, adr-031).

F5: register live-name SILENT delistings (Trendlyne ohlcv AND Bhavcopy both stop >30d before the
    latest bar => genuinely delisted, e.g. GSPL merged 2026-05). Mirrors the detector now baked into
    build_ca_factor.py, applied here without rerunning the full (expensive) CA detection.
F3: refresh delistings.ever_mcap_cr for dead names that the rebuild just added to pit_mcap_dead.

Idempotent. Run AFTER rebuild_pit_mcap_ca.py, with windfall-api/web stopped (opens RW).
"""
from __future__ import annotations
import sys
import duckdb

TL = sys.argv[1] if len(sys.argv) > 1 else "/mnt/storage/websites/windfall-labs/backend/data/trendlyne.duckdb"
BC = sys.argv[2] if len(sys.argv) > 2 else "/mnt/storage/websites/windfall-labs/backend/data/bhavcopy.duckdb"
con = duckdb.connect(TL)
con.execute(f"ATTACH '{BC}' AS bc (READ_ONLY)")
q = lambda s: con.execute(s).fetchall()

before = q("SELECT count(*) FROM delistings")[0][0]

# F5 — live silent delistings
con.execute(r"""
    INSERT INTO delistings (symbol, last_date, last_raw_close, ever_mcap_cr, ca_uncertain)
    WITH live AS (SELECT pk, upper(nsecode) sym FROM stocks WHERE nsecode<>''),
         bc_last AS (SELECT upper(regexp_replace(ticker,'\.NS$','')) sym, max(date) d
                     FROM bc.bhavcopy_prices WHERE series='EQ' AND close>0 GROUP BY 1),
         bc_max AS (SELECT max(date) d FROM bc.bhavcopy_prices WHERE series='EQ'),
         ohlcv_max AS (SELECT max(date) d FROM ohlcv),
         live_last AS (SELECT l.sym, max(y.date) last_date, arg_max(y.close,y.date) last_close
                       FROM ohlcv y JOIN live l USING(pk) GROUP BY 1)
    SELECT ll.sym, ll.last_date, ll.last_close,
           (SELECT max(p.mcap_cr) FROM pit_mcap p JOIN live l USING(pk) WHERE l.sym=ll.sym),
           FALSE
    FROM live_last ll JOIN bc_last bl USING(sym), bc_max, ohlcv_max
    WHERE ll.last_date < ohlcv_max.d - 30 AND bl.d < bc_max.d - 30
      AND ll.sym NOT IN (SELECT symbol FROM delistings)""")

added = q("""SELECT symbol, last_date, round(last_raw_close,1), round(ever_mcap_cr,0)
             FROM delistings WHERE symbol IN (
               WITH live AS (SELECT pk, upper(nsecode) sym FROM stocks WHERE nsecode<>''),
                    bc_last AS (SELECT upper(regexp_replace(ticker,'\\.NS$','')) sym, max(date) d
                                FROM bc.bhavcopy_prices WHERE series='EQ' AND close>0 GROUP BY 1),
                    bc_max AS (SELECT max(date) d FROM bc.bhavcopy_prices WHERE series='EQ'),
                    ohlcv_max AS (SELECT max(date) d FROM ohlcv),
                    live_last AS (SELECT l.sym, max(y.date) last_date FROM ohlcv y JOIN live l USING(pk) GROUP BY 1)
               SELECT ll.sym FROM live_last ll JOIN bc_last bl USING(sym), bc_max, ohlcv_max
               WHERE ll.last_date < ohlcv_max.d - 30 AND bl.d < bc_max.d - 30)""")
print(f"F5 live silent-delisting rows now in registry: {len(added)}")
for r in added:
    print("   ", r)

# F3 — refresh ever_mcap_cr for dead names now present in pit_mcap_dead (seeded loss-makers had NULL)
n_upd = con.execute("""
    UPDATE delistings SET ever_mcap_cr = (
        SELECT max(d.mcap_cr) FROM pit_mcap_dead d WHERE upper(d.sym)=upper(delistings.symbol))
    WHERE ever_mcap_cr IS NULL
      AND upper(symbol) IN (SELECT DISTINCT upper(sym) FROM pit_mcap_dead)""").fetchall()
refreshed = q("""SELECT symbol, round(ever_mcap_cr,0) FROM delistings
    WHERE upper(symbol) IN ('DHFL','BHUSANSTL','KFA','EDUCOMP','BINANIIND','RNAVAL','MONNETISPA','FCONSUMER','DEWANHOUS')
    ORDER BY symbol""")
print("\nF3 refreshed ever_mcap_cr for seeded dead names:")
for r in refreshed:
    print("   ", r)

after = q("SELECT count(*) FROM delistings")[0][0]
print(f"\ndelistings rows: {before} -> {after}")
con.close()
