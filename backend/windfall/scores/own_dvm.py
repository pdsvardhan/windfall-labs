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
# Durability is Piotroski-DOMINATED in Trendlyne's score: a least-squares fit of their durability on
# our snapshot inputs (held-out test) put Piotroski's weight ~3x any other and reached ~0.88 — our old
# ROE-led 0.20-Piotroski blend only hit ~0.55. Piotroski leads; eps-growth + low pledge + ROA follow.
# (ROE/OPM are collinear with these and near-zero in the fit; ROCE/D-E are screener-sourced and add
# cross-source noise vs Trendlyne's own-data target, so they are NOT in the live-match blend.)
DURABILITY_W = {"piotroski": 0.45, "pledge": 0.18, "eps_growth": 0.15, "roa": 0.12, "opm": 0.05, "np_qtr_yoy": 0.05}
# PEG leads the valuation blend: it is the strongest single predictor of Trendlyne's valuation score
# (Spearman ~0.67 on the 2026-06-18 snapshot, vs ~0.46 PE / ~0.41 PB / ~0.40 PE-to-sector). PE-to-sector
# was DROPPED (v1.1): a held-out least-squares fit gave it a NEGATIVE weight (redundant/noisy vs raw PE),
# and dropping it lifted the blend from ~0.41 to ~0.44 — the data ceiling. (Trendlyne valuation also uses
# forward-PE / EV-EBITDA / dividend-yield / self-history, none of which we have, so ~0.44 is the cap
# until those are sourced; the stock's own-history percentile was tested and does NOT help cross-sectionally.)
VALUATION_W = {"peg": 0.45, "pe": 0.30, "pb": 0.25}


def momentum_own(roc63, roc126, roc252, rsi14, rel_strength126) -> pd.DataFrame | None:
    """Price-only momentum score (fully backtestable)."""
    return _blend_pct([
        (roc63, MOMENTUM_W["roc63"]), (roc126, MOMENTUM_W["roc126"]),
        (roc252, MOMENTUM_W["roc252"]), (rsi14, MOMENTUM_W["rsi14"]),
        (rel_strength126, MOMENTUM_W["rel_strength126"]),
    ])


def durability_own(roe, roa, piotroski, opm, np_qtr_yoy, promoter_pledge,
                   eps_growth=None) -> pd.DataFrame | None:
    """Financial-quality score, Piotroski-led to track Trendlyne's durability (~0.86 on the snapshot,
    up from ~0.55). Lower promoter pledge is better, so it enters negated. `roe` is accepted for
    backward-compatibility but carries ~0 weight (collinear with Piotroski/ROA in Trendlyne's score);
    `eps_growth` is the growth-quality input. Inputs that are NaN drop out and the rest renormalize, so
    historical backtests (where piotroski/pledge/eps_growth are snapshot-only) fall back to ROA/OPM."""
    neg_pledge = (-promoter_pledge) if promoter_pledge is not None else None
    return _blend_pct([
        (piotroski, DURABILITY_W["piotroski"]), (neg_pledge, DURABILITY_W["pledge"]),
        (eps_growth, DURABILITY_W["eps_growth"]), (roa, DURABILITY_W["roa"]),
        (opm, DURABILITY_W["opm"]), (np_qtr_yoy, DURABILITY_W["np_qtr_yoy"]),
    ])


def valuation_own(pe, pb, pe_to_sector, peg=None) -> pd.DataFrame | None:
    """Cheapness score (cross-sectional). Every ratio enters NEGATED (cheaper = higher score) and is
    guarded > 0: a non-positive PE/PB/PEG/PE-to-sector (loss-maker, negative net worth) is undefined
    cheapness, so it drops from that component and the remaining weights renormalize — it is never
    scored as 'cheap'. (Negating an un-guarded negative ratio was the bug that made the old blend rank
    loss-makers as attractive and dragged it below its own components.)

    `peg` (P/E ÷ EPS-growth%) is the growth-adjusted cheapness Trendlyne leans on most; pass None to
    omit it. `pe_to_sector` is accepted for backward-compatibility but NOT used (v1.1: a held-out fit
    gave it a negative weight — redundant with raw PE — and dropping it raised the match to the ~0.44
    data ceiling). Reaching higher needs inputs we don't have (forward-PE / EV-EBITDA / dividend yield)."""
    def neg_pos(x):
        return (-x.where(x > 0)) if x is not None else None
    return _blend_pct([
        (neg_pos(peg), VALUATION_W["peg"]),
        (neg_pos(pe), VALUATION_W["pe"]),
        (neg_pos(pb), VALUATION_W["pb"]),
    ])
