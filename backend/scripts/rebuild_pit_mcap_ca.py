"""iter-28: rebuild pit_mcap / pit_mcap_dead with split/bonus-correct market caps.

Root cause of the old bug: pit_mcap used raw Bhavcopy price x (NP/EPS) shares. But Trendlyne's EPS
reflects a split on an INCONSISTENT date across names — EICHERMOT's 10:1 stepped at the 2020-06-30
period-end (EPS raw) while BEL's 2017 10:1 was BACK-adjusted (its 2016 EPS already shows post-split
shares). Pairing those mis-timed shares with the raw price made post/pre-split mcap 10x wrong.

Correct identity: historical mcap(t) = raw_price(t) x shares(t), and shares(t) = current_shares x
adj_factor(t) (shares grow by exactly the CA ratio on each ex-date). Since adj_close = raw x
adj_factor, this is simply:

    mcap(t) = adjusted_close(t) x current_shares

- LIVE names: adjusted_close = Trendlyne `ohlcv.close` (its EXACT split+bonus adjustment, validated
  in adr-014 vs Bhavcopy) -> no detector needed, ground-truth accurate.
- DEAD names: adjusted_close = raw Bhavcopy x ca_factor.adj_factor (our derived CA master).
- current_shares = the latest NP/EPS share count (live) or latest screener share count (dead).

Known limitation (documented, second-order): current_shares is held constant back through history, so
genuine share issuance/buyback over time is not separately modeled — immaterial vs the CA error this
fixes, and vs the Rs500cr membership threshold. (The previous code had BOTH issuance drift AND the
10x CA error; this removes the dominant one.)
"""
from __future__ import annotations

import sys
import duckdb

TL = sys.argv[1] if len(sys.argv) > 1 else "/mnt/storage/websites/windfall-labs/backend/data/trendlyne.duckdb"
BC = sys.argv[2] if len(sys.argv) > 2 else "/mnt/storage/websites/windfall-labs/backend/data/bhavcopy.duckdb"
SC = sys.argv[3] if len(sys.argv) > 3 else "/mnt/storage/websites/windfall-labs/backend/data/screener_fundamentals.duckdb"

con = duckdb.connect(TL)
con.execute(f"ATTACH '{BC}' AS bc (READ_ONLY)")
con.execute(f"ATTACH '{SC}' AS sc (READ_ONLY)")
q = lambda s: con.execute(s).fetchall()

con.execute("""CREATE OR REPLACE TEMP VIEW tl_sym AS
  SELECT pk, upper(nsecode) sym FROM stocks WHERE nsecode IS NOT NULL AND nsecode<>''
  UNION SELECT pk, upper(nse_symbol) FROM recovered_symbols WHERE nse_symbol IS NOT NULL AND nse_symbol<>''""")

# ── current share count per name: latest NP/EPS period (live) / latest screener period (dead) ─
con.execute("DROP TABLE IF EXISTS pit_shares")
con.execute("""CREATE TABLE pit_shares AS
  WITH npq AS (SELECT pk,date,value v FROM pnl_quarterly WHERE metric='NP_TTM'),
       epq AS (SELECT pk,date,value v FROM pnl_quarterly WHERE metric='EPS_TTM' AND value>0),
       qtr AS (SELECT npq.pk, npq.date from_date, npq.v/epq.v shares_cr FROM npq JOIN epq USING(pk,date)),
       npa AS (SELECT pk,date,value v FROM pnl_annual WHERE metric='NP_A'),
       epa AS (SELECT pk,date,value v FROM pnl_annual WHERE metric='EPS_A' AND value>0),
       ann AS (SELECT npa.pk, npa.date from_date, npa.v/epa.v shares_cr FROM npa JOIN epa USING(pk,date)),
       eps_derived AS (SELECT * FROM qtr WHERE shares_cr>0 UNION SELECT * FROM ann WHERE shares_cr>0),
       -- iter-12 (#73 / adr-026): loss-makers have EPS<=0, so NP/EPS yields no share count and they
       -- drop out of pit_mcap and the universe entirely (Swiggy, Meesho, Ola Electric, FirstCry, ...).
       -- Fall back to the current mcap snapshot / latest adjusted close — the SAME constant-current-
       -- shares identity used to build pit_mcap below (mcap = adj_close x current_shares). Only for
       -- pks with NO eps-derived shares, so profitable names are untouched.
       fallback AS (
         SELECT s.pk, lc.from_date, s.mcap / lc.last_close AS shares_cr
         FROM stocks s
         JOIN (SELECT pk, min(date) AS from_date, arg_max(close, date) AS last_close
               FROM ohlcv GROUP BY pk) lc ON lc.pk = s.pk
         WHERE s.mcap > 0 AND lc.last_close > 0
           AND s.pk NOT IN (SELECT pk FROM eps_derived)
       )
  SELECT * FROM eps_derived
  UNION ALL
  SELECT * FROM fallback""")
con.execute("""CREATE OR REPLACE TEMP VIEW shares_now AS
  SELECT pk, arg_max(shares_cr, from_date) AS shares_cr FROM pit_shares GROUP BY pk""")
con.execute("""CREATE OR REPLACE TEMP VIEW dead_shares_now AS
  SELECT upper(regexp_replace(ticker,'\\.NS$','')) sym,
         arg_max(coalesce(net_profit_owner,net_profit)/eps, period_end) AS shares_cr
  FROM sc.fundamentals_history
  WHERE eps>0 AND coalesce(net_profit_owner,net_profit)>0
    AND upper(regexp_replace(ticker,'\\.NS$','')) IN (SELECT sym FROM dead_names)
  GROUP BY 1""")

# ── pit_mcap (live): Trendlyne adjusted close x current shares ────────────────────────────────
# raw_close (for audit) via a hash join, not a per-row correlated lookup.
con.execute("""CREATE OR REPLACE TEMP VIEW bc_raw AS
  SELECT m.pk, b.date, b.close AS raw_close
  FROM bc.bhavcopy_prices b JOIN tl_sym m ON upper(regexp_replace(b.ticker,'\\.NS$',''))=m.sym
  WHERE b.series='EQ' AND b.close>0""")
con.execute("DROP TABLE IF EXISTS pit_mcap")
con.execute("""CREATE TABLE pit_mcap AS
  SELECT y.pk, y.date, r.raw_close, s.shares_cr, y.close * s.shares_cr AS mcap_cr
  FROM ohlcv y JOIN shares_now s USING(pk)
  LEFT JOIN bc_raw r ON r.pk=y.pk AND r.date=y.date
  WHERE y.close > 0""")
con.execute("CREATE INDEX idx_pitmcap ON pit_mcap(pk,date)")

# ── pit_mcap_dead: raw Bhavcopy x derived adj_factor x current shares ─────────────────────────
con.execute("""CREATE OR REPLACE TEMP VIEW dead_adj AS
  SELECT p.sym, p.date, p.close raw_close,
         coalesce((SELECT f.adj_factor FROM ca_factor f
                   WHERE f.ticker=p.sym AND f.from_date<=p.date ORDER BY f.from_date DESC LIMIT 1), 1.0)
           AS adj_factor
  FROM (SELECT upper(regexp_replace(ticker,'\\.NS$','')) sym, date, close
        FROM bc.bhavcopy_prices WHERE series='EQ' AND close>0
          AND upper(regexp_replace(ticker,'\\.NS$','')) IN (SELECT sym FROM dead_names)) p""")
con.execute("DROP TABLE IF EXISTS pit_mcap_dead")
con.execute("""CREATE TABLE pit_mcap_dead AS
  SELECT d.sym, d.date, d.raw_close, s.shares_cr,
         d.raw_close * d.adj_factor * s.shares_cr AS mcap_cr
  FROM dead_adj d JOIN dead_shares_now s USING(sym)""")
con.execute("CREATE INDEX idx_pmd ON pit_mcap_dead(sym, date)")

# ── capstone membership ───────────────────────────────────────────────────────────────────────
con.execute("DROP TABLE IF EXISTS universe_membership")
con.execute("""CREATE TABLE universe_membership AS
  SELECT m.sym AS symbol, p.date, p.mcap_cr, 'live' AS source
  FROM pit_mcap p JOIN tl_sym m ON p.pk=m.pk WHERE p.mcap_cr IS NOT NULL
  UNION ALL
  SELECT sym AS symbol, date, mcap_cr, 'dead' AS source FROM pit_mcap_dead WHERE mcap_cr IS NOT NULL""")
con.execute("CREATE INDEX idx_um ON universe_membership(symbol, date)")

print("== rebuilt ==  pit_mcap:", q("SELECT count(*) FROM pit_mcap")[0][0],
      " pit_mcap_dead:", q("SELECT count(*) FROM pit_mcap_dead")[0][0],
      " membership:", q("SELECT count(*) FROM universe_membership")[0][0])

print("\n== smoothness across known 10:1 splits (mcap lakh-cr, must NOT step ~10x) ==")
for sym, win in [("EICHERMOT", ("2020-05", "2020-11")), ("BEL", ("2016-11", "2017-07")),
                 ("BAJFINANCE", ("2016-07", "2016-12")), ("TATASTEEL", ("2022-05", "2022-10"))]:
    pk = q(f"SELECT pk FROM stocks WHERE upper(nsecode)='{sym}'")[0][0]
    rows = q(f"""SELECT date_trunc('month',date) mo, round(arg_max(mcap_cr,date)/1e5,3) m
                 FROM pit_mcap WHERE pk={pk} AND strftime(date,'%Y-%m') BETWEEN '{win[0]}' AND '{win[1]}'
                 GROUP BY 1 ORDER BY 1""")
    print(f"   {sym:10s}", [(str(d)[:7], m) for d, m in rows])

print("\n== membership (>Rs500cr) by cross-section ==")
for d in ['2016-06-30', '2019-06-28', '2022-06-30', '2025-06-30']:
    r = q(f"""SELECT source, count(*) FROM
              (SELECT symbol, source, arg_max(mcap_cr,date) m FROM universe_membership
               WHERE date BETWEEN DATE '{d}'-14 AND DATE '{d}' GROUP BY symbol, source)
              WHERE m>500 GROUP BY source""")
    d2 = {s: n for s, n in r}
    print(f"   {d}: {d2.get('live',0)} live + {d2.get('dead',0)} dead = {sum(d2.values())} eligible")
con.close()
