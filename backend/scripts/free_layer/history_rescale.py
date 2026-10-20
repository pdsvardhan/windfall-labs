"""iter-200 (item 1461): how does Trendlyne's price history change between harvests?

Compares the current trendlyne.duckdb `ohlcv` with older snapshots kept on disk, on the dates both
hold. A name whose whole overlapping history moved by one constant factor was back-adjusted by
Trendlyne for an event after the older harvest; each such name is checked against NSE's corporate
actions (split/bonus ratios, and rights issues) between the two harvests.

Read-only: opens the snapshot files read-only; writes nothing.

    .venv/bin/python scripts/free_layer/history_rescale.py
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

DATA = Path(__file__).resolve().parents[2] / "data"
SNAPSHOTS = ["trendlyne.duckdb.bak", "trendlyne.duckdb.pre-refresh-2026-09-07-bak"]


def main() -> None:
    con = duckdb.connect(str(DATA / "free_layer.duckdb"), read_only=True)
    con.execute(f"ATTACH '{DATA / 'trendlyne.duckdb'}' AS cur (READ_ONLY)")
    ev = con.execute("""SELECT symbol, ex_date, kind FROM ca_events_nse WHERE ratio IS NOT NULL
                        UNION ALL SELECT symbol, ex_date, 'rights' FROM nse_ca WHERE kind = 'rights'""").fetchdf()
    ev["ex_date"] = pd.to_datetime(ev["ex_date"])
    for snap in SNAPSHOTS:
        path = DATA / snap
        if not path.exists():
            print(f"{snap}: not on disk")
            continue
        con.execute(f"ATTACH '{path}' AS old (READ_ONLY)")
        old_last = con.execute("SELECT max(date) FROM old.ohlcv").fetchone()[0]
        cur_last = con.execute("SELECT max(date) FROM cur.ohlcv").fetchone()[0]
        df = con.execute("""
            WITH sym AS (SELECT pk, upper(nsecode) s FROM cur.stocks WHERE nsecode <> '')
            SELECT sym.s AS symbol, median(c.close / o.close) AS f, stddev_samp(c.close / o.close) AS sd,
                   count(*) AS n
            FROM cur.ohlcv c JOIN old.ohlcv o USING (pk, date) JOIN sym USING (pk)
            WHERE o.close > 0 AND c.close > 0
            GROUP BY sym.s HAVING count(*) >= 20""").fetchdf()
        moved = df[(df["f"] - 1).abs() > 0.005]
        constant = moved[(moved["sd"] / moved["f"]) < 0.005]
        win = ev[(ev["ex_date"] > pd.Timestamp(old_last)) & (ev["ex_date"] <= pd.Timestamp(cur_last))]
        explained = constant[constant["symbol"].isin(set(win["symbol"]))]
        print(f"\n{snap} (harvest through {old_last}) vs current (through {cur_last}): "
              f"{len(df)} names compared")
        print(f"  whole history rescaled by one constant factor: {len(constant)}; "
              f"of these with an NSE split/bonus/rights event between the harvests: {len(explained)}")
        print(f"  history moved but not by one constant factor: {len(moved) - len(constant)}")
        for r in constant.sort_values("f").head(12).itertuples():
            k = win[win["symbol"] == r.symbol]["kind"].tolist()
            print(f"    {r.symbol:12s} x{r.f:.3f}  events: {k or '-'}")
        con.execute("DETACH old")
    con.close()


if __name__ == "__main__":
    main()
