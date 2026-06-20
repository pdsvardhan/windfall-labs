"""Phase 3: build result-announcement lag so period-end fundamentals are point-in-time-safe.
For each (pk, period_end), available_from = earliest board-meeting/result date after period_end
(within 100d) from result_dates; fallback = period_end + 45d (SEBI quarterly deadline)."""
import duckdb
TL = "/mnt/storage/websites/windfall-labs/backend/data/trendlyne.duckdb"
con = duckdb.connect(TL)  # rw
q = lambda s: con.execute(s).fetchall()

print("== result_dates.purpose (top) ==", q("SELECT purpose, count(*) FROM result_dates GROUP BY 1 ORDER BY 2 DESC LIMIT 10"))
print("== RELIANCE result_dates 2024 ==", [(str(d), p) for d, p in q("SELECT date,purpose FROM result_dates WHERE pk=1127 AND date BETWEEN DATE '2024-01-01' AND DATE '2024-12-31' ORDER BY date")])

con.execute("DROP TABLE IF EXISTS result_lag")
con.execute("""CREATE TABLE result_lag AS
  WITH qe AS (
      SELECT DISTINCT pk, date AS period_end FROM pnl_quarterly
      UNION SELECT DISTINCT pk, date FROM pnl_annual),
   m AS (
      SELECT q.pk, q.period_end, min(r.date) AS announce
      FROM qe q JOIN result_dates r
        ON r.pk=q.pk AND r.date > q.period_end AND r.date <= q.period_end + INTERVAL 100 DAY
      GROUP BY 1,2)
  SELECT qe.pk, qe.period_end,
         COALESCE(m.announce, qe.period_end + INTERVAL 45 DAY) AS available_from,
         (m.announce IS NOT NULL) AS matched,
         date_diff('day', qe.period_end, COALESCE(m.announce, qe.period_end + INTERVAL 45 DAY)) AS lag_days
  FROM qe LEFT JOIN m USING(pk, period_end)""")
con.execute("CREATE INDEX idx_rlag ON result_lag(pk, period_end)")

n = q("SELECT count(*) FROM result_lag")[0][0]
mt = q("SELECT count(*) FROM result_lag WHERE matched")[0][0]
print(f"\nresult_lag rows: {n}  matched to a real result date: {mt} ({100*mt/n:.0f}%)  fallback(+45d): {n-mt}")
print("lag_days (matched) median/p10/p90:",
      [int(x) for x in q("SELECT median(lag_days), quantile_cont(lag_days,0.1), quantile_cont(lag_days,0.9) FROM result_lag WHERE matched")[0]])
print("RELIANCE sample (period_end -> available_from, lag):",
      [(str(pe), str(af), int(l)) for pe,af,l in q("SELECT period_end, available_from, lag_days FROM result_lag WHERE pk=1127 AND period_end>=DATE '2024-01-01' ORDER BY period_end")])
con.close()
