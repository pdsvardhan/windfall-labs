"""Phase 2 (Level A): build point-in-time market-cap table in trendlyne.duckdb.
mcap(t) = Bhavcopy_raw_close(t) x shares(t)   [both RAW -> smooth across splits/bonuses]
shares(t) = NP/EPS (quarterly TTM 2016->, annual fallback 2000->), forward-filled via ASOF join.
Share count is public on the ex-date, so no look-ahead lag is needed for SHARES (unlike earnings)."""
import duckdb
TL = "/mnt/storage/websites/windfall-labs/backend/data/trendlyne.duckdb"
BC = "/mnt/storage/websites/windfall-labs/backend/data/bhavcopy.duckdb"
con = duckdb.connect(TL)  # read-write (no persistent writer on trendlyne.duckdb)
con.execute(f"ATTACH '{BC}' AS bc (READ_ONLY)")
q = lambda s: con.execute(s).fetchall()

con.execute("DROP TABLE IF EXISTS pit_mcap")
con.execute("DROP TABLE IF EXISTS pit_shares")
con.execute("""CREATE TEMP VIEW tl_sym AS
  SELECT pk, upper(nsecode) sym FROM stocks WHERE nsecode IS NOT NULL AND nsecode<>''
  UNION SELECT pk, upper(nse_symbol) FROM recovered_symbols WHERE nse_symbol IS NOT NULL AND nse_symbol<>''""")

# shares (crore) = NP/EPS, raw. quarterly TTM (2016->) UNION annual (2000->); both raw -> consistent.
con.execute("""CREATE TABLE pit_shares AS
  WITH npq AS (SELECT pk,date,value v FROM pnl_quarterly WHERE metric='NP_TTM'),
       epq AS (SELECT pk,date,value v FROM pnl_quarterly WHERE metric='EPS_TTM' AND value>0),
       qtr AS (SELECT npq.pk, npq.date from_date, npq.v/epq.v shares_cr FROM npq JOIN epq USING(pk,date)),
       npa AS (SELECT pk,date,value v FROM pnl_annual WHERE metric='NP_A'),
       epa AS (SELECT pk,date,value v FROM pnl_annual WHERE metric='EPS_A' AND value>0),
       ann AS (SELECT npa.pk, npa.date from_date, npa.v/epa.v shares_cr FROM npa JOIN epa USING(pk,date))
  SELECT * FROM qtr WHERE shares_cr>0
  UNION SELECT * FROM ann WHERE shares_cr>0""")

# Join Bhavcopy via ISIN (not the current symbol) so renamed companies get their FULL pre-rename
# price history -> correct point-in-time mcap & membership in the pre-rename window (adr-025).
# (e.g. NAVA's mcap pre-2022 comes from its NBVENTURES rows, same ISIN.)
con.execute("""CREATE TEMP VIEW tl_isin AS
  SELECT DISTINCT m.pk, bi.isin
  FROM tl_sym m JOIN (
    SELECT DISTINCT upper(regexp_replace(ticker,'\\.NS$','')) sym, isin
    FROM bc.bhavcopy_prices WHERE series='EQ' AND isin IS NOT NULL AND isin<>''
  ) bi ON bi.sym=m.sym""")
con.execute("""CREATE TEMP VIEW bc_px AS
  SELECT t.pk, b.date, b.close raw_close
  FROM bc.bhavcopy_prices b JOIN tl_isin t ON b.isin=t.isin
  WHERE b.series='EQ' AND b.close>0""")

con.execute("""CREATE TABLE pit_mcap AS
  SELECT p.pk, p.date, p.raw_close, s.shares_cr, p.raw_close*s.shares_cr AS mcap_cr
  FROM bc_px p ASOF JOIN pit_shares s ON p.pk=s.pk AND p.date >= s.from_date""")
con.execute("CREATE INDEX idx_pitmcap ON pit_mcap(pk,date)")

print("== pit_mcap built ==")
print("  rows:", q("SELECT count(*) FROM pit_mcap")[0][0], " distinct pk:", q("SELECT count(DISTINCT pk) FROM pit_mcap")[0][0],
      " date range:", q("SELECT min(date),max(date) FROM pit_mcap")[0])

print("\n== continuity across corporate actions (should be SMOOTH, no halving) ==")
for sym, win in [('RELIANCE', ("2024-07-01","2025-03-01")), ('HDFCBANK', ("2019-06-01","2020-03-01"))]:
    pk = q(f"SELECT pk FROM tl_sym WHERE sym='{sym}'")[0][0]
    rows = q(f"""SELECT date_trunc('month',date) mo, arg_max(mcap_cr,date)/1e5 m
                 FROM pit_mcap WHERE pk={pk} AND date BETWEEN DATE '{win[0]}' AND DATE '{win[1]}'
                 GROUP BY 1 ORDER BY 1""")
    print(f"  {sym} mcap (lakh-cr) by month:", [(str(d)[:7], round(m,2)) for d,m in rows])

print("\n== point-in-time membership counts (mcap > Rs500 Cr) at cross-sections ==")
for d in ['2015-06-30','2018-06-29','2020-06-30','2023-06-30','2026-06-12']:
    n = q(f"""SELECT count(*) FROM (SELECT pk, arg_max(mcap_cr,date) m FROM pit_mcap
              WHERE date BETWEEN DATE '{d}'-14 AND DATE '{d}' GROUP BY pk) WHERE m>500""")[0][0]
    print(f"  {d}: {n} stocks eligible (>Rs500 Cr)")

# sanity: how many TL universe stocks got a pit_mcap (coverage)
print("\n  coverage: pit_mcap pks =", q("SELECT count(DISTINCT pk) FROM pit_mcap")[0][0],
      "of 1,949 TL (rest = no Bhavcopy EQ price or no EPS>0)")
con.close()
