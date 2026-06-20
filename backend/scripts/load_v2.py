"""Phase 1: load v2 OHLCV (stocks + indices) into trendlyne.duckdb and verify
whether the large caps are present (orphan-pk test + Reliance fingerprint)."""
import duckdb
DB = "/mnt/storage/websites/windfall-labs/backend/data/trendlyne.duckdb"
V2 = "/mnt/storage/websites/windfall-labs/backend/data/trendlyne_data_v2"
con = duckdb.connect(DB)  # read-write; trendlyne.duckdb has no persistent writer (ONE-DOOR safe)
q = lambda s: con.execute(s).fetchall()

for t in ["ohlcv", "index_ohlcv", "index_map"]:
    con.execute(f"DROP TABLE IF EXISTS {t}")
con.execute(f"CREATE TABLE ohlcv AS SELECT * FROM read_csv('{V2}/ohlcv/*.csv', header=true, auto_detect=true, sample_size=-1, strict_mode=false)")
con.execute(f"CREATE TABLE index_ohlcv AS SELECT * FROM read_csv('{V2}/index_ohlcv.csv', header=true, auto_detect=true, sample_size=-1, strict_mode=false)")
con.execute(f"CREATE TABLE index_map AS SELECT * FROM read_csv('{V2}/index_map.csv', header=true, auto_detect=true, sample_size=-1, strict_mode=false)")

print("== loaded ==")
for t in ["ohlcv", "index_ohlcv", "index_map"]:
    info = con.execute(f"PRAGMA table_info('{t}')").fetchall()
    n = q(f"SELECT count(*) FROM {t}")[0][0]
    print(f"  {t:12s} {n:>11,}  [{' '.join(c[1]+':'+c[2] for c in info)}]")

print("\n== ohlcv coverage ==")
print("  distinct pk:", q("SELECT count(DISTINCT pk) FROM ohlcv")[0][0])
print("  date range :", q("SELECT min(date), max(date) FROM ohlcv")[0])
orphans = q("SELECT count(DISTINCT pk) FROM ohlcv WHERE pk NOT IN (SELECT pk FROM stocks)")[0][0]
print("  pk NOT in main stocks (orphans = candidate megacaps):", orphans)
if orphans:
    print("   sample orphan pks:", [r[0] for r in q("SELECT DISTINCT pk FROM ohlcv WHERE pk NOT IN (SELECT pk FROM stocks) LIMIT 25")])

print("\n== MEGACAP PRESENCE TEST ==")
rel = q("SELECT pk, date, close FROM ohlcv WHERE date BETWEEN '2024-09-25' AND '2024-10-05' "
        "AND close BETWEEN 1400 AND 1550 ORDER BY pk, date LIMIT 15")
print("  Reliance fingerprint (close~1471 around Sep-2024):", rel)
print("  highest recent close (>=2026-06-01):", q("SELECT pk,date,close FROM ohlcv WHERE date>='2026-06-01' ORDER BY close DESC LIMIT 5"))
print("  ohlcv pk count that ARE megacaps would show as orphans above ^")

print("\n== indices ==")
print("  index_map:", q("SELECT * FROM index_map ORDER BY pk"))
print("  index_ohlcv distinct pk:", q("SELECT count(DISTINCT pk) FROM index_ohlcv")[0][0],
      "range", q("SELECT min(date),max(date) FROM index_ohlcv")[0])
con.close()
