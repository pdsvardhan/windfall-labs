"""Engine-facing data audit of trendlyne.duckdb + PIT/identity layer.

Read-only (API opens the same file read_only, so safe to run live). Covers the 8
issue categories from docs/validation/SESSION-data-audit.md. Prints PASS / FLAG lines;
FLAG = candidate finding for the report's triage.

Run: cd backend && .venv/bin/python ../_staging/audit_engine.py
"""
from __future__ import annotations
import duckdb

TL = "/mnt/storage/websites/windfall-labs/backend/data/trendlyne.duckdb"
con = duckdb.connect(TL, read_only=True)
q = lambda s: con.execute(s).fetchall()
one = lambda s: con.execute(s).fetchone()

ASOF = one("SELECT MAX(date) FROM ohlcv")[0]
DVMAX = one("SELECT MAX(date) FROM dvm_history")[0]
print(f"==== ENGINE DATA AUDIT :: trendlyne.duckdb ====")
print(f"ohlcv last bar = {ASOF}   dvm last = {DVMAX}\n")

def hdr(s): print(f"\n########## {s} ##########")
def line(label, val, flag=False):
    print(f"  {'FLAG ' if flag else 'ok   '}{label:42s} {val}")

# ============================================================ 1. PRICES / SCORES
hdr("1. OHLCV (prices)")
n, npk, dmin, dmax = one("SELECT COUNT(*),COUNT(DISTINCT pk),MIN(date),MAX(date) FROM ohlcv")
line("rows / distinct_pk / range", f"{n:,} / {npk} / {dmin}..{dmax}")
dups = one("SELECT COUNT(*) FROM (SELECT pk,date,COUNT(*) c FROM ohlcv GROUP BY 1,2 HAVING c>1)")[0]
line("duplicate (pk,date)", dups, dups>0)
bad = one("""SELECT
  SUM((close<=0 OR close IS NULL)::INT), SUM((open<=0)::INT), SUM((high<low)::INT),
  SUM((volume<0)::INT), SUM((low<=0)::INT),
  SUM((high<close OR high<open OR low>close OR low>open)::INT)
  FROM ohlcv""")
line("close<=0/null", bad[0], bad[0]>0)
line("open<=0", bad[1], bad[1]>0)
line("high<low", bad[2], bad[2]>0)
line("volume<0", bad[3], bad[3]>0)
line("low<=0", bad[4], bad[4]>0)
line("OHLC inconsistency (h<c/o or l>c/o)", bad[5], bad[5]>0)
zerovol = one("SELECT COUNT(*) FROM ohlcv WHERE volume=0")[0]
line("volume=0 bars", f"{zerovol:,}", zerovol>50000)
# adjusted-return outliers: ohlcv is Trendlyne-adjusted, so >40% one-day moves are suspect (un-adjusted CA)
out = q("""WITH r AS (SELECT pk,date,close, close/LAG(close) OVER (PARTITION BY pk ORDER BY date)-1 ret FROM ohlcv)
  SELECT COUNT(*) FROM r WHERE ABS(ret)>0.4""")[0][0]
line(">40% one-day move (post-adj suspicious)", out, out>500)
out_ex = q("""WITH r AS (SELECT pk,date,close, close/LAG(close) OVER (PARTITION BY pk ORDER BY date)-1 ret FROM ohlcv)
  SELECT s.nsecode,r.date,ROUND(r.ret*100,0) FROM r JOIN stocks s USING(pk) WHERE ABS(ret)>2.0 ORDER BY ABS(ret) DESC LIMIT 12""")
print("       worst >200% single-day jumps (likely missed split/bonus):")
for sym,d,rp in out_ex: print(f"         {sym} {d} {rp}%")
# date holes: trading-day gaps inside a name's own window
holes = one("""WITH g AS (SELECT pk,date, date - LAG(date) OVER (PARTITION BY pk ORDER BY date) gap FROM ohlcv)
  SELECT COUNT(*) FROM g WHERE gap > 10""")[0]
line("intra-history gaps >10 calendar days", f"{holes:,}", holes>5000)
# staleness: names whose last bar is well before the global max but NOT in delistings (silent dropouts)
silent = q("""WITH lb AS (SELECT pk,MAX(date) mx FROM ohlcv GROUP BY pk)
  SELECT s.nsecode, lb.mx FROM lb JOIN stocks s USING(pk)
  WHERE lb.mx < DATE '%s' - 30
    AND upper(s.nsecode) NOT IN (SELECT upper(symbol) FROM delistings)
  ORDER BY lb.mx DESC""" % ASOF)
line("live names stale >30d, NOT in delistings (silent)", len(silent), len(silent)>0)
for sym,mx in silent[:20]: print(f"         {sym}: last {mx}")
thin = one("SELECT COUNT(*) FROM (SELECT pk,COUNT(*) c FROM ohlcv GROUP BY pk HAVING c<250)")[0]
line("names with <250 bars (~<1yr)", thin)

hdr("1b. DVM_HISTORY")
scores = q("SELECT score,COUNT(*),COUNT(DISTINCT pk),MIN(date),MAX(date),MIN(value),MAX(value) FROM dvm_history GROUP BY 1 ORDER BY 1")
for sc,c,pk,mn,mx,vmn,vmx in scores:
    line(f"score={sc}", f"rows={c:,} pk={pk} {mn}..{mx} val[{vmn},{vmx}]", (vmn<0 or vmx>100))
dvm_dup = one("SELECT COUNT(*) FROM (SELECT pk,score,date,COUNT(*) c FROM dvm_history GROUP BY 1,2,3 HAVING c>1)")[0]
line("duplicate (pk,score,date)", dvm_dup, dvm_dup>0)
# stocks.d_now/v_now/m_now vs latest dvm_history
drift = q("""WITH latest AS (SELECT pk,score,arg_max(value,date) v FROM dvm_history GROUP BY 1,2)
  SELECT COUNT(*) FROM (
    SELECT s.pk, s.d_now, MAX(CASE WHEN l.score='durability' THEN l.v END) ld
    FROM stocks s LEFT JOIN latest l ON l.pk=s.pk GROUP BY 1,2)
  WHERE d_now IS NOT NULL AND ld IS NOT NULL AND ABS(d_now-ld)>1""")[0][0]
line("stocks.d_now vs latest dvm durability mismatch>1", drift, drift>50)

hdr("1c. VALUATION_RATIOS")
vm = q("SELECT metric,COUNT(*),COUNT(DISTINCT pk),MIN(value),MAX(value),SUM((value<=0)::INT) FROM valuation_ratios GROUP BY 1 ORDER BY 1")
for m,c,pk,vmn,vmx,nle in vm:
    line(f"metric={m}", f"rows={c:,} pk={pk} [{vmn:.1f},{vmx:.1f}] <=0:{nle:,}")
vr_dup = one("SELECT COUNT(*) FROM (SELECT pk,metric,date,COUNT(*) c FROM valuation_ratios GROUP BY 1,2,3 HAVING c>1)")[0]
line("duplicate (pk,metric,date)", vr_dup, vr_dup>0)
ext = one("SELECT COUNT(*) FROM valuation_ratios WHERE metric LIKE 'PE%' AND value>2000")[0]
line("PE-type > 2000 (extreme)", ext, ext>0)

hdr("1d. INDEX_OHLCV (benchmarks)")
idx = q("""SELECT m.name, COUNT(*), MIN(o.date), MAX(o.date), SUM((o.close<=0 OR o.close IS NULL)::INT)
  FROM index_ohlcv o JOIN index_map m USING(pk) GROUP BY 1 ORDER BY 1""")
for nm,c,mn,mx,bad0 in idx:
    line(f"{nm}", f"rows={c:,} {mn}..{mx} close<=0:{bad0}", c<2000 or bad0>0)
# the VARCHAR open/high/low columns
ohl_type = one("SELECT data_type FROM information_schema.columns WHERE table_name='index_ohlcv' AND column_name='open'")[0]
line("index_ohlcv.open column type", ohl_type, ohl_type!='DOUBLE')

# ============================================================ 2/3. FUNDAMENTALS + PIT
hdr("2/3. FUNDAMENTALS tables — metrics, ranges, look-ahead")
for tbl in ["pnl_annual","pnl_quarterly","balance_sheet","cashflow","ratios_annual","growth_quality","ownership","financials_other"]:
    n,pk,mn,mx = one(f"SELECT COUNT(*),COUNT(DISTINCT pk),MIN(date),MAX(date) FROM {tbl}")
    fut = one(f"SELECT COUNT(*) FROM {tbl} WHERE date > DATE '{ASOF}'")[0]
    nnull = one(f"SELECT COUNT(*) FROM {tbl} WHERE value IS NULL")[0]
    line(f"{tbl}", f"rows={n:,} pk={pk} {mn}..{mx} future-dated:{fut} null-val:{nnull}", fut>0)
print("       distinct metrics per table:")
for tbl in ["pnl_annual","pnl_quarterly","ratios_annual","growth_quality","cashflow","shareholding_summary"]:
    col = "category" if tbl=="shareholding_summary" else "metric"
    ms = [r[0] for r in q(f"SELECT DISTINCT {col} FROM {tbl} ORDER BY 1")]
    print(f"         {tbl}: {ms}")

hdr("3. RESULT_LAG (anti-look-ahead gate)")
n,pk = one("SELECT COUNT(*),COUNT(DISTINCT pk) FROM result_lag")
line("rows / distinct_pk", f"{n:,} / {pk}")
unmatched = one("SELECT COUNT(*) FROM result_lag WHERE matched=false")[0]
line("unmatched rows (fallback lag used)", f"{unmatched:,}", unmatched>n*0.5)
negl = one("SELECT COUNT(*) FROM result_lag WHERE lag_days < 0")[0]
line("NEGATIVE lag_days (LOOK-AHEAD!)", negl, negl>0)
zerol = one("SELECT COUNT(*) FROM result_lag WHERE lag_days = 0")[0]
line("zero lag_days (same-day availability)", zerol, zerol>0)
lagdist = q("SELECT MIN(lag_days),quantile_cont(lag_days,0.5),MAX(lag_days),AVG(lag_days) FROM result_lag WHERE matched=true")
line("matched lag_days min/median/max/avg", f"{lagdist[0]}")
futav = one("SELECT COUNT(*) FROM result_lag WHERE available_from > TIMESTAMP '%s'" % ASOF)[0]
line("available_from in the future (vs asof)", futav)
# fundamentals rows with NO result_lag match (would be invisible to result-gated readers)
orphan = one("""SELECT COUNT(*) FROM (SELECT DISTINCT pk,date FROM ratios_annual) f
  LEFT JOIN result_lag r ON r.pk=f.pk AND r.period_end=f.date WHERE r.pk IS NULL""")[0]
line("ratios_annual (pk,date) with NO result_lag", f"{orphan:,}", orphan>0)

hdr("3b. CORPORATE ACTIONS / result_dates future-dating")
ca_fut = one("SELECT COUNT(*) FROM corporate_actions WHERE ex_date > DATE '%s'" % ASOF)[0]
line("corporate_actions future ex_date", ca_fut)
rd_fut = one("SELECT COUNT(*) FROM result_dates WHERE date > DATE '%s'" % ASOF)[0]
line("result_dates future (announced upcoming)", rd_fut)
cae_fut = one("SELECT COUNT(*) FROM ca_events WHERE ex_date > DATE '%s'" % ASOF)[0]
line("ca_events future ex_date", cae_fut)

# ============================================================ 4. SURVIVORSHIP
hdr("4. SURVIVORSHIP (dead/delisted completeness)")
line("delistings rows", one("SELECT COUNT(*) FROM delistings")[0])
line("dead_names rows", one("SELECT COUNT(*) FROM dead_names")[0])
# dead names present in pit_mcap_dead (have price+mcap)
dead_with_mcap = one("SELECT COUNT(DISTINCT sym) FROM pit_mcap_dead")[0]
dead_total = one("SELECT COUNT(*) FROM dead_names")[0]
line("dead_names with mcap in pit_mcap_dead", f"{dead_with_mcap}/{dead_total}", dead_with_mcap<dead_total)
dead_no_mcap = q("""SELECT sym FROM dead_names WHERE upper(sym) NOT IN (SELECT upper(sym) FROM pit_mcap_dead) ORDER BY 1""")
for r in dead_no_mcap[:25]: print(f"         no mcap: {r[0]}")
# delistings vs dead_names overlap
ca_unc = one("SELECT COUNT(*) FROM delistings WHERE ca_uncertain")[0]
line("delistings with ca_uncertain=true", ca_unc)
# membership includes dead?
um_src = q("SELECT source,COUNT(DISTINCT symbol),COUNT(*) FROM universe_membership GROUP BY 1")
for s,ns,nr in um_src: line(f"universe_membership source={s}", f"symbols={ns} rows={nr:,}")

# ============================================================ 5. IDENTITY / JOIN
hdr("5. IDENTITY / JOIN integrity")
line("stocks rows / distinct nsecode", f"{one('SELECT COUNT(*) FROM stocks')[0]} / {one('SELECT COUNT(DISTINCT nsecode) FROM stocks')[0]}")
blank = one("SELECT COUNT(*) FROM stocks WHERE nsecode IS NULL OR nsecode=''")[0]
line("stocks blank nsecode", blank, blank>0)
numtok = one("SELECT COUNT(*) FROM stocks WHERE nsecode ~ '^[0-9]+$'")[0]
line("stocks numeric-token nsecode", numtok, numtok>0)
if numtok:
    for r in q("SELECT pk,nsecode,name FROM stocks WHERE nsecode ~ '^[0-9]+$' LIMIT 10"): print(f"         {r}")
dup_code = q("SELECT upper(nsecode) c,COUNT(*) n FROM stocks WHERE nsecode<>'' GROUP BY 1 HAVING n>1 ORDER BY n DESC LIMIT 10")
line("duplicate nsecode (collisions)", len(dup_code), len(dup_code)>0)
for c,nn in dup_code[:10]: print(f"         {c} x{nn}")
# pk in dvm/valuation/ohlcv not in stocks (orphan pks)
for tbl in ["ohlcv","dvm_history","valuation_ratios"]:
    orph = one(f"SELECT COUNT(DISTINCT pk) FROM {tbl} WHERE pk NOT IN (SELECT pk FROM stocks)")[0]
    line(f"{tbl} pks NOT in stocks", orph, orph>0)
# stocks with NO ohlcv
no_px = q("SELECT pk,nsecode,name FROM stocks WHERE pk NOT IN (SELECT DISTINCT pk FROM ohlcv) ORDER BY 2")
line("stocks with NO ohlcv prices", len(no_px), len(no_px)>0)
for r in no_px[:15]: print(f"         {r[1]} (pk={r[0]}) {r[2]}")
# recovered_symbols overlap with stocks nsecode
rs_overlap = one("SELECT COUNT(*) FROM recovered_symbols r WHERE upper(r.nse_symbol) IN (SELECT upper(nsecode) FROM stocks WHERE nsecode<>'')")[0]
line("recovered_symbols also in stocks.nsecode", rs_overlap)
# rename_map health
rm = one("SELECT COUNT(*),SUM((live_in_tl=false)::INT) FROM rename_map")
line("rename_map rows / live_not_in_tl", f"{rm[0]} / {rm[1]}")
# sector_map unknowns
unk = one("SELECT COUNT(*) FROM sector_map WHERE sector IS NULL OR sector='' OR sector='Unknown'")[0]
line("sector_map Unknown/blank", unk, unk>50)

# ============================================================ 6. CROSS-STORE
hdr("6. CROSS-STORE consistency")
line("ohlcv max vs dvm max vs val max vs um max",
     f"{ASOF} / {DVMAX} / {one('SELECT MAX(date) FROM valuation_ratios')[0]} / {one('SELECT MAX(date) FROM universe_membership')[0]}")
skew = (DVMAX - ASOF).days if hasattr(DVMAX-ASOF,'days') else 0
line("dvm leads ohlcv by (days)", skew, skew>3)
# pit_mcap 1:1 with ohlcv?
pm = one("SELECT COUNT(*) FROM ohlcv o LEFT JOIN pit_mcap p ON p.pk=o.pk AND p.date=o.date WHERE p.pk IS NULL")[0]
line("ohlcv bars with NO pit_mcap", f"{pm:,}", pm>0)
pm_raw_null = one("SELECT COUNT(*) FROM pit_mcap WHERE raw_close IS NULL")[0]
line("pit_mcap rows missing raw_close (audit col)", f"{pm_raw_null:,}")
pm_bad = one("SELECT COUNT(*) FROM pit_mcap WHERE mcap_cr<=0 OR mcap_cr IS NULL")[0]
line("pit_mcap mcap_cr<=0/null", pm_bad, pm_bad>0)

# ============================================================ 7. PIT_SHARES / loss-maker fallback
hdr("7. PIT_SHARES & loss-maker fallback (adr-026)")
ps_bad = one("SELECT COUNT(*) FROM pit_shares WHERE shares_cr<=0 OR shares_cr IS NULL")[0]
line("pit_shares shares_cr<=0/null", ps_bad, ps_bad>0)
# names whose ONLY shares come from the fallback (no eps-derived) -> constant-shares back through history
fb = one("""WITH eps_pk AS (
    SELECT DISTINCT pk FROM pnl_quarterly WHERE metric='EPS_TTM' AND value>0
    UNION SELECT DISTINCT pk FROM pnl_annual WHERE metric='EPS_A' AND value>0)
  SELECT COUNT(DISTINCT pk) FROM pit_shares WHERE pk NOT IN (SELECT pk FROM eps_pk)""")[0]
line("pks on loss-maker fallback only (constant shares)", fb)
# extreme shares (data error proxy)
ps_ext = q("SELECT s.nsecode, MAX(p.shares_cr) FROM pit_shares p JOIN stocks s USING(pk) GROUP BY 1 ORDER BY 2 DESC LIMIT 5")
print("       largest shares_cr (sanity):", [(a,round(b,1)) for a,b in ps_ext])

# ============================================================ 8. KNOWN PRIOR ITEMS
hdr("8. RE-VERIFY known prior items")
# 8a CA smoothness across known 10:1 splits (must NOT step ~10x)
print("  CA-smoothness (mcap lakh-cr monthly; flat across split = good):")
for sym,win in [("EICHERMOT",("2020-05","2020-11")),("BEL",("2016-11","2017-07")),("TATASTEEL",("2022-05","2022-10"))]:
    pkrow = q(f"SELECT pk FROM stocks WHERE upper(nsecode)='{sym}'")
    if not pkrow: print(f"     {sym}: not found"); continue
    pk=pkrow[0][0]
    rows=q(f"""SELECT strftime(date,'%Y-%m') mo, round(arg_max(mcap_cr,date)/1e5,3) m FROM pit_mcap
      WHERE pk={pk} AND strftime(date,'%Y-%m') BETWEEN '{win[0]}' AND '{win[1]}' GROUP BY 1 ORDER BY 1""")
    print(f"     {sym:10s}", [(d,m) for d,m in rows])
# 8b 200DMA coverage: names with >=200 bars before their 'recent' window (proxy: total bars)
dma_short = one("SELECT COUNT(*) FROM (SELECT pk,COUNT(*) c FROM ohlcv GROUP BY pk HAVING c<200)")[0]
line("names with <200 total bars (200DMA blind)", dma_short)
# 8c negative-PE guard: how many PE_TTM<=0 (resolve masks these, todo #36)
peneg = one("SELECT COUNT(*),COUNT(DISTINCT pk) FROM valuation_ratios WHERE metric='PE_TTM' AND value<=0")
line("valuation PE_TTM<=0 rows / names (masked in resolve)", f"{peneg[0]:,} / {peneg[1]}")
# 8d valuation ceiling input availability: PBV coverage
pbv = one("SELECT COUNT(DISTINCT pk) FROM valuation_ratios WHERE metric='PBV_A'")[0]
line("PBV_A distinct pk (valuation input coverage)", pbv)

con.close()
print("\n==== AUDIT COMPLETE ====")
