"""Capstone: unified survivorship-free PIT membership = live survivors (pit_mcap, pk->symbol)
UNION dead names (pit_mcap_dead, symbol). Symbol-keyed; membership = mcap_cr > 500."""
import duckdb
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
