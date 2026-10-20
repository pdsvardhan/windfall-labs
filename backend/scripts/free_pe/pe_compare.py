"""iter-201 (item 1464): the engine's free P/E vs Trendlyne's, month by month.

  pe     = adjusted close / latest ANNUAL EPS from the screener.in store, known 120 days after the
           fiscal period end (fundamentals.screener_history_panel) — free, survivorship-free,
           financials (banks/NBFCs) excluded by the store's rules
  tl_pe  = Trendlyne's daily TTM P/E (valuation_ratios PE_TTM), survivors-only

At every month-end from Jul 2016, on that date's point-in-time Rs500cr universe:
  coverage of each (and why one has a name the other lacks: delisted, financial, missing),
  Spearman rank correlation where both exist,
  overlap of the CHEAPEST quintile — what a value ranking actually acts on.

Read-only (screener / trendlyne / bhavcopy stores). Run with WINDFALL_DATA_DIR pointing at the
live data dir and WINDFALL_DB at a COPY of windfall.duckdb (the price layer reads corporate actions
from the meta DB, which the api holds - ONE DOOR); nothing writes there except data/free_pe.duckdb.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from windfall.data import fundamentals as fund  # noqa: E402
from windfall.data import trendlyne_store as ts  # noqa: E402

DATA = Path(os.environ["WINDFALL_DATA_DIR"])
OUT = DATA / "free_pe.duckdb"


def main() -> None:
    months = pd.date_range("2016-07-31", "2026-08-31", freq="ME")
    uni = {d: ts.pit_universe(d.date()) for d in months}
    names = sorted(set().union(*uni.values()))
    print(f"{len(months)} month-ends, {len(names)} names ever in the universe")
    close = ts.adjusted_close_panel(names, start="2016-05-01", end="2026-08-31").ffill()
    idx = close.index
    eps = fund.screener_history_panel("eps", idx, list(close.columns))
    own = close / eps.reindex(index=idx, columns=close.columns).where(lambda x: x > 0)
    tl = ts.valuation_panel("tl_pe", list(close.columns))
    tl = tl.reindex(idx.union(tl.index)).ffill(limit=10).reindex(idx)
    tl = tl.where(tl > 0)
    dead = {r[0] for r in ts._con().execute("SELECT symbol FROM delistings").fetchall()}
    fin = {r[0].replace(".NS", "") for r in duckdb.connect(str(DATA / "screener_fundamentals.duckdb"),
                                                            read_only=True).execute(
        "SELECT DISTINCT ticker FROM fundamentals_history WHERE confidence='excluded-financial' "
        "OR is_financial").fetchall()}

    rows = []
    for d in months:
        day = idx[idx <= d][-1]
        u = [s for s in uni[d] if s in close.columns]
        o = own.loc[day, u].dropna()
        # the point-in-time universe (adr-050) includes delisted names Trendlyne never carried
        t = tl.loc[day].reindex(u).dropna() if not tl.empty else pd.Series(dtype=float)
        both = o.index.intersection(t.index)
        rho = o[both].rank().corr(t[both].rank()) if len(both) > 20 else np.nan
        q_o = set(o[both].nsmallest(len(both) // 5).index)
        q_t = set(t[both].nsmallest(len(both) // 5).index)
        only_t, only_o = set(t.index) - set(o.index), set(o.index) - set(t.index)
        rows.append({"date": d.date(), "universe": len(u), "own": len(o), "tl": len(t),
                     "both": len(both), "spearman": rho,
                     "cheap_quintile_overlap": len(q_o & q_t) / max(len(q_t), 1),
                     "tl_only": len(only_t), "tl_only_financial": len(only_t & fin),
                     "own_only": len(only_o), "own_only_dead": len(only_o & dead),
                     "dead_in_universe": len(set(u) & dead)})
    m = pd.DataFrame(rows)
    con = duckdb.connect(str(OUT))
    con.register("m", m)
    con.execute("CREATE OR REPLACE TABLE pe_agreement AS SELECT * FROM m")
    con.close()
    print("\nyear | universe | own pe | tl_pe | both | rank corr | cheapest-fifth overlap | "
          "tl-only (of which banks/NBFCs) | own-only (of which delisted)")
    m["year"] = pd.to_datetime(m["date"]).dt.year
    for y, g in m.groupby("year"):
        print(f"  {y} | {g.universe.mean():.0f} | {g.own.mean():.0f} | {g.tl.mean():.0f} | "
              f"{g.both.mean():.0f} | {g.spearman.mean():.2f} | {g.cheap_quintile_overlap.mean():.0%} | "
              f"{g.tl_only.mean():.0f} ({g.tl_only_financial.mean():.0f}) | "
              f"{g.own_only.mean():.0f} ({g.own_only_dead.mean():.0f})")
    print(f"\nall months: rank corr {m.spearman.mean():.2f} (min {m.spearman.min():.2f}), "
          f"cheapest-fifth overlap {m.cheap_quintile_overlap.mean():.0%}")


if __name__ == "__main__":
    main()
