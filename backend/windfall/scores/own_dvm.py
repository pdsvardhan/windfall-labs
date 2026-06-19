"""Our own, reproducible Durability / Valuation / Momentum scores (0-100).

These are OURS — computed from data we hold, with a transparent formula — not Trendlyne's
proprietary DVM. We validate against Trendlyne's snapshot scores (scores/validate.py) and tune.

Each score is a cross-sectional percentile blend: at each date, percentile-rank every input
across all stocks, weight-blend (renormalizing over the inputs that have a value), and scale to
0-100. Higher = better (more durable / cheaper / stronger momentum), matching Trendlyne's sense.

- momentum_own: 100% price-derived -> fully backtestable over the entire price history.
- durability_own / valuation_own: from point-in-time fundamentals -> NaN before the snapshot,
  so they are snapshot-gated like any fundamental feature (the data-readiness gate flags this).

The recipe follows the standard public description of DVM:
  Durability  = financial quality: ROE, ROA, Piotroski, operating margin, profit growth, low pledge.
  Valuation   = cheapness vs peers/sector: low P/E, low P/B, low P/E-to-sector (loss-makers excluded).
  Momentum    = price trend: 3/6/12m returns, RSI, relative strength vs the index.
Weights live here and are easy to tune against the validation correlations.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _blend_pct(items: list[tuple[pd.DataFrame, float]]) -> pd.DataFrame | None:
    """Cross-sectional percentile blend -> 0-100. `items` is [(panel, weight), ...], higher=better.

    Each panel is percentile-ranked across columns (stocks) within each row (date); contributions
    are summed and divided by the per-cell weight of inputs that actually had a value, so a missing
    input drops out and the rest renormalize. Result is scaled to 0-100.
    """
    blended: pd.DataFrame | None = None
    wsum: pd.DataFrame | None = None
    for panel, w in items:
        if panel is None:
            continue
        pct = panel.rank(axis=1, pct=True)
        contrib = (pct * w).fillna(0.0)
        present = pct.notna().astype(float) * w
        blended = contrib if blended is None else blended.add(contrib)
        wsum = present if wsum is None else wsum.add(present)
    if blended is None or wsum is None:
        return None
    return blended.divide(wsum.replace(0.0, np.nan)) * 100.0


# Default weights (tunable against validation correlations).
MOMENTUM_W = {"roc63": 0.20, "roc126": 0.25, "roc252": 0.25, "rsi14": 0.15, "rel_strength126": 0.15}
DURABILITY_W = {"roe": 0.25, "roa": 0.15, "piotroski": 0.20, "opm": 0.15, "np_qtr_yoy": 0.10, "pledge": 0.15}
# PEG leads the valuation blend: it is the strongest single predictor of Trendlyne's valuation score
# (Spearman ~0.67 on the 2026-06-18 snapshot, vs ~0.46 PE / ~0.40 PE-to-sector / ~0.30 PB), because
# Trendlyne valuation is growth-adjusted. PB is the weakest, so it is downweighted.
VALUATION_W = {"peg": 0.40, "pe_to_sector": 0.25, "pe": 0.20, "pb": 0.15}


def momentum_own(roc63, roc126, roc252, rsi14, rel_strength126) -> pd.DataFrame | None:
    """Price-only momentum score (fully backtestable)."""
    return _blend_pct([
        (roc63, MOMENTUM_W["roc63"]), (roc126, MOMENTUM_W["roc126"]),
        (roc252, MOMENTUM_W["roc252"]), (rsi14, MOMENTUM_W["rsi14"]),
        (rel_strength126, MOMENTUM_W["rel_strength126"]),
    ])


def durability_own(roe, roa, piotroski, opm, np_qtr_yoy, promoter_pledge) -> pd.DataFrame | None:
    """Financial-quality score. Lower promoter pledge is better, so it enters negated."""
    neg_pledge = (-promoter_pledge) if promoter_pledge is not None else None
    return _blend_pct([
        (roe, DURABILITY_W["roe"]), (roa, DURABILITY_W["roa"]),
        (piotroski, DURABILITY_W["piotroski"]), (opm, DURABILITY_W["opm"]),
        (np_qtr_yoy, DURABILITY_W["np_qtr_yoy"]), (neg_pledge, DURABILITY_W["pledge"]),
    ])


def valuation_own(pe, pb, pe_to_sector, peg=None) -> pd.DataFrame | None:
    """Cheapness score (cross-sectional). Every ratio enters NEGATED (cheaper = higher score) and is
    guarded > 0: a non-positive PE/PB/PEG/PE-to-sector (loss-maker, negative net worth) is undefined
    cheapness, so it drops from that component and the remaining weights renormalize — it is never
    scored as 'cheap'. (Negating an un-guarded negative ratio was the bug that made the old blend rank
    loss-makers as attractive and dragged it below its own components.)

    `peg` (P/E ÷ EPS-growth%) is the growth-adjusted cheapness Trendlyne leans on most; pass None to
    omit it. The remaining Trendlyne ingredient — current multiple vs the stock's own 5–10yr history —
    is a follow-up, unlocked once the screener-history overlap is wide enough to compute it."""
    def neg_pos(x):
        return (-x.where(x > 0)) if x is not None else None
    return _blend_pct([
        (neg_pos(peg), VALUATION_W["peg"]),
        (neg_pos(pe_to_sector), VALUATION_W["pe_to_sector"]),
        (neg_pos(pe), VALUATION_W["pe"]),
        (neg_pos(pb), VALUATION_W["pb"]),
    ])
