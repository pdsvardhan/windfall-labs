"""iter-200 (item 1462, part 2): score both Rs500cr universes against NSE's OFFICIAL market cap.

SUPERSEDED by explain_membership.py: this first scoring counted renames, SME names and REITs/InvITs as
"wrongly in" for the current universe (its 18.4% headline is not a fair figure). Kept for the record.

From 2024-02-29 the NSE MCAP file gives each listed security's official market cap on that day,
so at every month-end since then there is a ground truth: the set of NSE names with mcap > Rs500cr.
Scored against it:
  current   tl.universe_membership (Trendlyne adjusted close x NP/EPS-derived current shares)
  free      Trendlyne adjusted close x that month's NSE issue size (point-in-time, not "current")
Also lists who the current universe admits that NSE's official number does not, with both numbers.

Read-only on trendlyne; reads data/free_layer.duckdb (nse_mcap from compare_mcap.py).

    .venv/bin/python scripts/free_layer/membership_truth.py
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

DATA = Path(__file__).resolve().parents[2] / "data"
FREE, TL = DATA / "free_layer.duckdb", DATA / "trendlyne.duckdb"
FLOOR = 500.0


def main() -> None:
    con = duckdb.connect(str(FREE))
    con.execute(f"ATTACH '{TL}' AS tl (READ_ONLY)")
    dates = [r[0] for r in con.execute(
        "SELECT DISTINCT date FROM nse_mcap WHERE date <= DATE '2026-08-28' ORDER BY 1").fetchall()]
    rows, examples = [], None
    for d in dates:
        truth = set(con.execute("""
            SELECT symbol FROM nse_mcap WHERE date = ? AND series IN ('EQ', 'BE')
            GROUP BY symbol HAVING max(mcap_rs) / 1e7 > ?""", [d, FLOOR]).fetchdf()["symbol"])
        cur = con.execute("""
            SELECT symbol, m FROM (SELECT symbol, arg_max(mcap_cr, date) m FROM tl.universe_membership
                                   WHERE date BETWEEN CAST(? AS DATE) - 14 AND CAST(? AS DATE)
                                   GROUP BY symbol)""", [d, d]).fetchdf()
        cur_set = set(cur.loc[cur["m"] > FLOOR, "symbol"])
        free = con.execute("""
            WITH sym AS (SELECT upper(nsecode) s, pk FROM tl.stocks WHERE nsecode <> ''),
                 sh AS (SELECT symbol, max(issue_size) issue_size FROM nse_mcap
                        WHERE date = ? AND series IN ('EQ', 'BE') GROUP BY symbol),
                 px AS (SELECT pk, arg_max(close, date) c FROM tl.ohlcv
                        WHERE date BETWEEN CAST(? AS DATE) - 14 AND CAST(? AS DATE) GROUP BY pk)
            SELECT sym.s AS symbol, px.c * sh.issue_size / 1e7 AS m
            FROM px JOIN sym USING (pk) JOIN sh ON sh.symbol = sym.s""", [d, d, d]).fetchdf()
        free_set = set(free.loc[free["m"] > FLOOR, "symbol"])
        # Only names the price layer can see at all are comparable (NSE lists SME/BSE-dual names too).
        seen = set(cur["symbol"]) | set(free["symbol"])
        t = truth & seen

        def score(s):
            return len(s & t), len(s - t), len(t - s)

        ct, cf, cm = score(cur_set & seen)
        ft, ff, fm = score(free_set)
        rows.append({"date": d, "truth": len(t), "cur_ok": ct, "cur_wrong_in": cf, "cur_missed": cm,
                     "free_ok": ft, "free_wrong_in": ff, "free_missed": fm})
        if d == dates[-1]:
            off = cur[cur["symbol"].isin(cur_set - t)].merge(
                con.execute("""SELECT symbol, max(mcap_rs) / 1e7 nse_mcap_cr FROM nse_mcap
                               WHERE date = ? GROUP BY symbol""", [d]).fetchdf(), how="left")
            examples = off.sort_values("m", ascending=False)
    m = pd.DataFrame(rows)
    print("month-end | official >Rs500cr (seen) | current: right / wrongly in / missed | "
          "free: right / wrongly in / missed")
    for r in m.itertuples():
        print(f"  {r.date} | {r.truth} | {r.cur_ok} / {r.cur_wrong_in} / {r.cur_missed} | "
              f"{r.free_ok} / {r.free_wrong_in} / {r.free_missed}")
    tot = m.sum(numeric_only=True)
    print(f"\ntotal over {len(m)} month-ends: current wrong {int(tot.cur_wrong_in + tot.cur_missed)}"
          f" ({(tot.cur_wrong_in + tot.cur_missed) / tot.truth:.1%} of official), "
          f"free wrong {int(tot.free_wrong_in + tot.free_missed)} "
          f"({(tot.free_wrong_in + tot.free_missed) / tot.truth:.1%})")
    print(f"\ncurrent universe admits but NSE's official mcap says < Rs500cr, at {dates[-1]} "
          f"(top 20 by our mcap):")
    for r in examples.head(20).itertuples():
        print(f"  {r.symbol:12s} ours Rs{r.m:,.0f}cr  NSE official "
              + (f"Rs{r.nse_mcap_cr:,.0f}cr" if pd.notna(r.nse_mcap_cr) else "— (not in NSE file)"))
    con.register("m", m)
    con.execute("CREATE OR REPLACE TABLE membership_truth AS SELECT * FROM m")
    con.close()


if __name__ == "__main__":
    main()
