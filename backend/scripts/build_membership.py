"""Capstone: unified survivorship-free PIT membership = live survivors (pit_mcap, pk->symbol)
UNION dead names (pit_mcap_dead, symbol). Symbol-keyed; membership = mcap_cr > 500."""
import sys

import duckdb

# Retired with the frozen price history (adr-050, iter-204). This rebuild derives point-in-time market
# cap from Trendlyne's adjusted close x a CURRENT share count; with the close frozen and the share
# count refreshed every month, a re-run would rewrite pre-2024 membership each time (and loss-makers'
# fallback count = today's mcap / a months-old close). From 2024-02-01 membership is NSE's official
# market cap (scripts/nse_mcap_ingest.py). Pass --force-after-adr-050 only to rebuild deliberately.
if "--force-after-adr-050" not in sys.argv:
    sys.exit("retired by adr-050 (frozen price history) — see the comment above; "
             "--force-after-adr-050 to run anyway")
sys.argv = [a for a in sys.argv if a != "--force-after-adr-050"]
TL = "/mnt/storage/websites/windfall-labs/backend/data/trendlyne.duckdb"
con = duckdb.connect(TL)
q = lambda s: con.execute(s).fetchall()
con.execute("""CREATE TEMP VIEW tl_sym AS
  SELECT pk, upper(nsecode) sym FROM stocks WHERE nsecode IS NOT NULL AND nsecode<>''
  UNION SELECT pk, upper(nse_symbol) FROM recovered_symbols WHERE nse_symbol IS NOT NULL AND nse_symbol<>''""")
con.execute("DROP TABLE IF EXISTS universe_membership")
con.execute("""CREATE TABLE universe_membership AS
  SELECT m.sym AS symbol, p.date, p.mcap_cr, 'live' AS source
  FROM pit_mcap p JOIN tl_sym m ON p.pk=m.pk
  UNION ALL
  SELECT sym AS symbol, date, mcap_cr, 'dead' AS source FROM pit_mcap_dead""")
con.execute("CREATE INDEX idx_um ON universe_membership(symbol, date)")

print("universe_membership rows:", q("SELECT count(*) FROM universe_membership")[0][0],
      " distinct symbols:", q("SELECT count(DISTINCT symbol) FROM universe_membership")[0][0])
print("\n== survivorship-free membership (>Rs500 Cr) by cross-section: live + dead ==")
for d in ['2016-06-30', '2019-06-28', '2022-06-30', '2025-06-30']:
    r = q(f"""SELECT source, count(*) FROM
              (SELECT symbol, source, arg_max(mcap_cr,date) m FROM universe_membership
               WHERE date BETWEEN DATE '{d}'-14 AND DATE '{d}' GROUP BY symbol, source)
              WHERE m>500 GROUP BY source""")
    d2 = {s: n for s, n in r}
    live, dead = d2.get('live', 0), d2.get('dead', 0)
    print(f"  {d}: {live} live + {dead} dead = {live+dead} eligible (was survivorship-biased without the +{dead} dead)")
con.close()
