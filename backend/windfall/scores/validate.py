"""Validate our own D/V/M against Trendlyne's snapshot scores.

The Trendlyne snapshot already carries Trendlyne's own durability / valuation / momentum_score
columns. We compute OUR scores as of the snapshot date and rank-correlate (Spearman) each
component against Trendlyne's. High correlation means our reproducible formula tracks theirs;
where it doesn't, the weights in own_dvm.py are the knobs to tune. This is the verify/tune loop
that lets us trust our own scores over history once we no longer have Trendlyne's.
"""
from __future__ import annotations

import pandas as pd

from .. import signals as ind
from ..data import fundamentals as fund
from ..data import store
from ..data.store import connect
from ..data.universe import benchmark_ticker
from . import own_dvm as own


def _spearman(ours: pd.Series, theirs: pd.Series) -> dict:
    df = pd.DataFrame({"ours": ours, "theirs": theirs}).dropna()
    rho = float(df["ours"].corr(df["theirs"], method="spearman")) if len(df) > 2 else None
    return {"spearman": round(rho, 4) if rho is not None else None, "n": int(len(df))}


def validate_own_dvm(snapshot_date: str | None = None) -> dict:
    snaps = fund.snapshots()
    if not snaps:
        return {"error": "no fundamentals snapshot loaded"}
    snap = snapshot_date or snaps[-1]

    con = connect()
    fdf = con.execute(
        "SELECT ticker, durability, valuation, momentum_score, roe, roa, piotroski, opm, "
        "np_qtr_yoy, promoter_pledge, pe, pb, sector_pe "
        "FROM fundamentals WHERE snapshot_date = ?", [snap]).fetchdf()
    if fdf.empty:
        return {"error": f"no fundamentals at snapshot {snap}"}
    f = fdf.set_index("ticker")
    ts = pd.Timestamp(snap)

    def row(series: pd.Series) -> pd.DataFrame:
        return pd.DataFrame([series.to_dict()], index=[ts])

    # our Durability / Valuation from the snapshot fundamentals (cross-sectional)
    pe_to_sector = f["pe"] / f["sector_pe"].replace(0.0, pd.NA)
    dur_own = own.durability_own(row(f["roe"]), row(f["roa"]), row(f["piotroski"]),
                                 row(f["opm"]), row(f["np_qtr_yoy"]), row(f["promoter_pledge"])).iloc[0]
    val_own = own.valuation_own(row(f["pe"]), row(f["pb"]), row(pe_to_sector)).iloc[0]

    # our Momentum from price history up to the snapshot (price-only)
    tickers = list(f.index)
    close = store.price_panel("close", tickers, "2014-01-01", snap, adjusted=True)
    bt = benchmark_ticker("NIFTY500")
    bpanel = store.price_panel("close", [bt], "2014-01-01", snap, adjusted=True)
    benchmark = bpanel[bt] if bt in bpanel.columns else close.mean(axis=1)
    mom_panel = own.momentum_own(ind.roc(close, 63), ind.roc(close, 126), ind.roc(close, 252),
                                 ind.rsi(close, 14), ind.relative_strength(close, benchmark, 126))
    mom_own = mom_panel.dropna(how="all").iloc[-1] if mom_panel is not None and not mom_panel.dropna(how="all").empty else pd.Series(dtype=float)

    return {
        "snapshot_date": str(snap),
        "universe": int(len(f)),
        "components": {
            "durability": _spearman(dur_own, f["durability"]),
            "valuation": _spearman(val_own, f["valuation"]),
            "momentum": _spearman(mom_own.reindex(f.index), f["momentum_score"]),
        },
        "note": ("Spearman rank correlation of our score vs Trendlyne's, on the snapshot "
                 "cross-section. Tune weights in scores/own_dvm.py to raise these."),
    }
