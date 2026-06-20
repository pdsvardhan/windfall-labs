"""Phase 3 part B: reconcile Trendlyne annual fundamentals vs our screener.in scrape
on the survivor overlap (independent cross-check of the fundamental layer)."""
import duckdb
TL = "/mnt/storage/websites/windfall-labs/backend/data/trendlyne.duckdb"
SC = "/mnt/storage/websites/windfall-labs/backend/data/screener_fundamentals.duckdb"
con = duckdb.connect()
con.execute(f"ATTACH '{TL}' AS tl (READ_ONLY)")
con.execute(f"ATTACH '{SC}' AS sc (READ_ONLY)")
q = lambda s: con.execute(s).fetchall()

# TL annual revenue (SR_A) & net profit (NP_A) -> symbol+fiscal-year
con.execute("""CREATE TEMP VIEW tl_sym AS
  SELECT pk, upper(nsecode) sym FROM tl.stocks WHERE nsecode IS NOT NULL AND nsecode<>''""")
con.execute("""CREATE TEMP VIEW tl_fund AS
  SELECT m.sym, extract(year from a.date) yr, a.metric, a.value
  FROM tl.pnl_annual a JOIN tl_sym m USING(pk) WHERE a.metric IN ('SR_A','NP_A')""")
con.execute("""CREATE TEMP VIEW tlf AS
  SELECT sym, yr, max(value) FILTER(WHERE metric='SR_A') tl_rev, max(value) FILTER(WHERE metric='NP_A') tl_np
  FROM tl_fund GROUP BY 1,2""")
# screener annual (period_end year) revenue + owner NP
con.execute("""CREATE TEMP VIEW scf AS
  SELECT upper(regexp_replace(ticker,'\\.NS$','')) sym, extract(year from period_end) yr,
         max(revenue) sc_rev, max(coalesce(net_profit_owner,net_profit)) sc_np
  FROM sc.fundamentals_history GROUP BY 1,2""")
con.execute("""CREATE TEMP VIEW j AS
  SELECT t.sym, t.yr, t.tl_rev, s.sc_rev, t.tl_np, s.sc_np
  FROM tlf t JOIN scf s USING(sym, yr)
  WHERE t.tl_rev>0 AND s.sc_rev>0""")

n = q("SELECT count(*) FROM j")[0][0]
print(f"matched (symbol, fiscal-year) pairs: {n}")
print("REVENUE agreement (TL vs screener):")
print("  median |%diff|:", round(q("SELECT median(abs(tl_rev-sc_rev)/sc_rev*100) FROM j")[0][0],2),
      " within 2%/5%:", q("SELECT count(*) FILTER(WHERE abs(tl_rev-sc_rev)/sc_rev<0.02), count(*) FILTER(WHERE abs(tl_rev-sc_rev)/sc_rev<0.05) FROM j")[0])
print("NET PROFIT (owner) agreement:")
print("  median |%diff|:", round(q("SELECT median(abs(tl_np-sc_np)/abs(nullif(sc_np,0))*100) FROM j WHERE sc_np<>0")[0][0],2),
      " within 5%/10%:", q("SELECT count(*) FILTER(WHERE abs(tl_np-sc_np)/abs(sc_np)<0.05), count(*) FILTER(WHERE abs(tl_np-sc_np)/abs(sc_np)<0.10) FROM j WHERE sc_np<>0")[0])
print("  worst revenue mismatches:",
      [(s,int(y),round(tr,0),round(sr,0)) for s,y,tr,sr in q("SELECT sym,yr,tl_rev,sc_rev FROM j ORDER BY abs(tl_rev-sc_rev)/sc_rev DESC LIMIT 8")])
con.close()
