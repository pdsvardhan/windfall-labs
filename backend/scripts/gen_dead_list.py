"""Write the 256 ISIN-dead symbols (peak turnover>50cr, not in TL, ISIN stopped) to a CSV
for the screener scraper, and also persist a rename_map + dead_names registry into trendlyne.duckdb."""
import duckdb, csv
TL = "/mnt/storage/websites/windfall-labs/backend/data/trendlyne.duckdb"
BC = "/mnt/storage/websites/windfall-labs/backend/data/bhavcopy.duckdb"
OUT = "/mnt/storage/websites/windfall-labs/backend/data/dead_names.csv"
con = duckdb.connect(TL)  # rw (to write rename_map / dead_names)
con.execute(f"ATTACH '{BC}' AS bc (READ_ONLY)")
q = lambda s: con.execute(s).fetchall()

con.execute("""CREATE TEMP VIEW tl_syms AS
  SELECT upper(nsecode) sym FROM stocks WHERE nsecode IS NOT NULL AND nsecode<>''
  UNION SELECT upper(nse_symbol) FROM recovered_symbols WHERE nse_symbol IS NOT NULL AND nse_symbol<>''""")
con.execute("""CREATE TEMP VIEW bcsym AS
  SELECT upper(regexp_replace(ticker,'\\.NS$','')) sym, isin, min(date) f, max(date) l, max(close*volume) pt
  FROM bc.bhavcopy_prices WHERE series='EQ' AND isin IS NOT NULL AND isin<>'' GROUP BY 1,2""")
con.execute("CREATE TEMP VIEW isin_active AS SELECT isin, max(l) last_any, arg_max(sym,l) latest_sym FROM bcsym GROUP BY isin")
con.execute("""CREATE TEMP VIEW dead AS
  SELECT b.sym, b.isin, b.f, b.l, b.pt, ia.last_any, ia.latest_sym
  FROM bcsym b JOIN isin_active ia ON b.isin=ia.isin
  WHERE b.l < DATE '2025-12-01' AND b.pt>5e8 AND b.sym NOT IN (SELECT sym FROM tl_syms)""")

# rename_map: old dead symbol -> live successor (ISIN still active)
con.execute("DROP TABLE IF EXISTS rename_map")
con.execute("""CREATE TABLE rename_map AS
  SELECT sym AS old_sym, isin, latest_sym AS live_sym,
         (latest_sym IN (SELECT sym FROM tl_syms)) AS live_in_tl
  FROM dead WHERE last_any >= DATE '2026-01-01'""")
# dead_names registry: ISIN truly stopped
con.execute("DROP TABLE IF EXISTS dead_names")
con.execute("""CREATE TABLE dead_names AS
  SELECT sym, isin, f AS first_date, l AS last_date, pt AS peak_turnover
  FROM dead WHERE last_any < DATE '2026-01-01'""")

rn = q("SELECT count(*) FROM rename_map")[0][0]
dn = q("SELECT count(*) FROM dead_names")[0][0]
syms = [r[0] for r in q("SELECT sym FROM dead_names ORDER BY peak_turnover DESC")]
with open(OUT, "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["symbol"])
    for s in syms:
        w.writerow([s])
print(f"rename_map rows: {rn}  dead_names rows: {dn}  -> wrote {len(syms)} symbols to {OUT}")
con.close()
