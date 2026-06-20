"""Level B finalize: build pit_mcap_dead (symbol-keyed) for the dead names just scraped.
mcap_cr = Bhavcopy_raw_close x (net_profit_owner/eps)  [shares from screener, raw price from Bhavcopy]."""
import duckdb
TL = "/mnt/storage/websites/windfall-labs/backend/data/trendlyne.duckdb"
BC = "/mnt/storage/websites/windfall-labs/backend/data/bhavcopy.duckdb"
SC = "/mnt/storage/websites/windfall-labs/backend/data/screener_fundamentals.duckdb"
con = duckdb.connect(TL)  # rw -> create pit_mcap_dead in trendlyne.duckdb
con.execute(f"ATTACH '{BC}' AS bc (READ_ONLY)")
con.execute(f"ATTACH '{SC}' AS sc (READ_ONLY)")
q = lambda s: con.execute(s).fetchall()

# dead-name shares from screener (owner NP / eps), per period
con.execute("""CREATE TEMP VIEW dead_shares AS
  SELECT upper(regexp_replace(ticker,'\\.NS$','')) sym, period_end AS from_date,
         coalesce(net_profit_owner, net_profit)/eps AS shares_cr
  FROM sc.fundamentals_history
  WHERE eps > 0 AND coalesce(net_profit_owner, net_profit) > 0
    AND upper(regexp_replace(ticker,'\\.NS$','')) IN (SELECT sym FROM dead_names)""")
# bhavcopy raw price for dead names
con.execute("""CREATE TEMP VIEW dead_px AS
  SELECT upper(regexp_replace(ticker,'\\.NS$','')) sym, date, close raw_close
  FROM bc.bhavcopy_prices WHERE series='EQ' AND close>0
    AND upper(regexp_replace(ticker,'\\.NS$','')) IN (SELECT sym FROM dead_names)""")

con.execute("DROP TABLE IF EXISTS pit_mcap_dead")
con.execute("""CREATE TABLE pit_mcap_dead AS
  SELECT p.sym, p.date, p.raw_close, s.shares_cr, p.raw_close*s.shares_cr AS mcap_cr
  FROM dead_px p ASOF JOIN dead_shares s ON p.sym=s.sym AND p.date >= s.from_date""")
con.execute("CREATE INDEX idx_pmd ON pit_mcap_dead(sym, date)")

print("== pit_mcap_dead ==")
print("  rows:", q("SELECT count(*) FROM pit_mcap_dead")[0][0],
      " dead symbols with mcap:", q("SELECT count(DISTINCT sym) FROM pit_mcap_dead")[0][0],
      " of 256 dead")
print("  date range:", q("SELECT min(date),max(date) FROM pit_mcap_dead")[0])
print("  sample (DHFL/RCOM/JETAIRWAYS last mcap, lakh-cr):",
      [(s, str(d), round(m/1e5,2)) for s,d,m in q("""SELECT sym, max(date), arg_max(mcap_cr,date)
         FROM pit_mcap_dead WHERE sym IN ('RCOM','JETAIRWAYS','HDIL','DHFL','RELCAPITAL') GROUP BY sym""")])
# how many dead names were >500cr at their peak (i.e. materially in-universe historically)
print("  dead names that ever exceeded Rs500cr:",
      q("SELECT count(*) FROM (SELECT sym, max(mcap_cr) m FROM pit_mcap_dead GROUP BY sym) WHERE m>500")[0][0])
con.close()
