"""iter-206 (#970): is the NSE-filings TTM P/E right? Checked against what we already trust.

For every symbol the fetch has stored, at month-ends from 2018:
  nse_pe  = back-adjusted close / TTM EPS from NSE filings, known on its broadcast date, EPS restated
            into today's share units for splits/bonuses after the filing        (nse_filings.pe_ttm_panel)
  tl_pe   = Trendlyne's daily TTM P/E (survivors only)
  pe      = the engine's own annual P/E from the screener.in store
and reports, per year: coverage of each, how close nse_pe is to tl_pe (median ratio, share within +-15%,
rank correlation) and to the annual pe, plus the names where nse_pe and tl_pe disagree most.

Read-only. Run with WINDFALL_DATA_DIR = live data dir and WINDFALL_DB = a COPY of windfall.duckdb.
Usage: python nse_ttm_validate.py [n_worst]
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from windfall.data import corp_actions  # noqa: E402
from windfall.data import fundamentals as fund  # noqa: E402
from windfall.data import nse_filings as nf  # noqa: E402
from windfall.data import trendlyne_store as ts  # noqa: E402

N_WORST = int(sys.argv[1]) if len(sys.argv) > 1 else 12

con = duckdb.connect(str(nf.DB_PATH), read_only=True)
q = nf.quarterly(con)
syms = sorted(q["symbol"].unique())
print(f"{len(syms)} symbols, {len(q)} single-quarter filings, "
      f"{q.period_end.min().date()}..{q.period_end.max().date()}; basis {q.basis.value_counts().to_dict()}")
ev = corp_actions.share_events(syms)
ttm = nf.ttm_eps(q, ev)
print(f"{len(ttm)} TTM points over {ttm.symbol.nunique()} symbols")

months = pd.date_range("2018-06-30", "2026-09-30", freq="ME")
close = ts.adjusted_close_panel(syms, start="2018-01-01", end="2026-10-25").ffill()
idx = close.index
nse = nf.pe_ttm_panel(close, ttm)
tl = ts.valuation_panel("tl_pe", list(close.columns))
tl = tl.reindex(idx.union(tl.index)).ffill(limit=10).reindex(idx)
tl = tl.where(tl > 0)
eps = fund.screener_history_panel("eps", idx, list(close.columns))
own = close / eps.reindex(index=idx, columns=close.columns).where(lambda x: x > 0) if eps is not None else None

rows, pairs = [], []
for d in months:
    day = idx[idx <= d][-1]
    a, b = nse.loc[day].dropna(), tl.loc[day].dropna()
    both = a.index.intersection(b.index)
    r = {"date": d, "nse": len(a), "tl": len(b), "both": len(both)}
    if len(both) >= 8:
        ratio = (a[both] / b[both])
        r.update(median_ratio=ratio.median(), within15=float(((ratio > 0.85) & (ratio < 1.15)).mean()),
                 rho_tl=a[both].rank().corr(b[both].rank()))
        pairs += [(d, s, a[s], b[s]) for s in both]
    if own is not None:
        o = own.loc[day].dropna()
        bo = a.index.intersection(o.index)
        r["both_own"] = len(bo)
        if len(bo) >= 8:
            r["rho_own"] = a[bo].rank().corr(o[bo].rank())
    rows.append(r)
m = pd.DataFrame(rows)
m["year"] = m.date.dt.year
print("\nyear | NSE covers | tl_pe covers | both | median nse/tl | within +-15% | rank corr vs tl | rank corr vs annual pe")
for y, g in m.groupby("year"):
    print(f"  {y} | {g.nse.mean():.0f} | {g.tl.mean():.0f} | {g.both.mean():.0f} | "
          f"{g.median_ratio.mean():.2f} | {g.within15.mean():.0%} | {g.rho_tl.mean():.2f} | {g.get('rho_own', pd.Series([np.nan])).mean():.2f}")

p = pd.DataFrame(pairs, columns=["date", "symbol", "nse", "tl"])
p["ratio"] = p.nse / p.tl
worst = (p.assign(dev=np.log(p.ratio).abs()).groupby("symbol")
         .agg(months=("dev", "size"), median_ratio=("ratio", "median"), mean_dev=("dev", "mean"))
         .sort_values("mean_dev", ascending=False).head(N_WORST))
print("\nsymbols where nse_pe and tl_pe disagree most (mean |log ratio|):")
print(worst.round(2).to_string())
print(f"\nall pairs: median nse/tl {p.ratio.median():.2f}, within +-15% {((p.ratio > .85) & (p.ratio < 1.15)).mean():.0%}, "
      f"within +-30% {((p.ratio > .7) & (p.ratio < 1.3)).mean():.0%}, n={len(p)}")
