"""Per-strategy data readiness: can this strategy be backtested, and from when?

Price-derived features have full history (the loaded price window). Fundamental features come
from Trendlyne snapshots and are NaN before the first snapshot. The distinction that matters:

- A fundamental in a hard FILTER makes the whole strategy *live-only* — the filter fails NaN
  historically, so a backtest holds nothing before the snapshot (today's dvm_monthly).
- A fundamental that appears only in the rank BLEND is blank-tolerant — the blend renormalizes
  over the factors that do have data, so the strategy still backtests on its price factors and
  the fundamental factor simply activates once snapshots exist.

So we can tell the owner, at strategy-creation, exactly what kind of evidence a strategy can
produce — which is the whole point of the platform.
"""
from __future__ import annotations

import re

from ..data import fundamentals as fund
from ..data import store
from .safe_eval import feature_names
from .schema import StrategyConfig

_PARAM = re.compile(r"^(sma|ema|roc|rsi|atr|adx|adtv|vol_avg|dist_high|rel_strength)\d+$")
_BASE = {"close", "open", "high", "low", "volume", "adj_close", "price"}
_SPECIAL = {"adtv_cr", "macd", "macd_signal", "macd_hist", "momentum_own"}  # momentum_own is price-only
_FUND = set(fund.NUMERIC_FIELDS) | {"pe_to_sector", "durability_own", "valuation_own"}  # fundamental-derived
# Fundamentals now backed by real screener history: durability inputs + computed valuation pe/pb (in
# SCREENER_HISTORY_FIELDS) + the own-scores (durability_own / valuation_own). 120d-lagged point-in-time
# over ~2006->present, NOT snapshot-gated — a strategy using only these IS backtestable.
_HIST_FUND = set(fund.SCREENER_HISTORY_FIELDS) | {"durability_own", "valuation_own"}
# Trendlyne full-history features (data_source="trendlyne"): DVM scores + valuation multiples are
# published daily (point-in-time by construction); raw fundamentals are result-lag-gated. All carry
# real history from 2016-06, so a trendlyne strategy is backtestable — never snapshot-gated.
_TL_DAILY = {"tl_durability", "tl_valuation", "tl_momentum", "tl_pe", "tl_peg", "tl_pbv"}
_TL_LAGGED = {"tl_roe", "tl_roce", "tl_de", "tl_opm", "tl_eps"}
_TL = _TL_DAILY | _TL_LAGGED
TL_HISTORY_FROM = "2016-06-10"


def _features(exprs: list[str]) -> set[str]:
    out: set[str] = set()
    for e in exprs:
        out |= set(feature_names(e))
    return out


def _classify(name: str) -> str:
    if name in _FUND:
        return "fundamental"
    if name in _BASE or name in _SPECIAL or _PARAM.match(name):
        return "price"
    return "unknown"


def data_readiness(cfg) -> dict:
    cfg = cfg if isinstance(cfg, StrategyConfig) else StrategyConfig(**cfg)

    filter_feats = _features(list(cfg.universe.filters) + list(cfg.entry_filters))
    rank_exprs = [rf.factor for rf in cfg.rank_blend] if cfg.rank_blend else [cfg.rank_by]
    rank_feats = _features(rank_exprs)
    all_feats = filter_feats | rank_feats

    # Trendlyne survivorship-free layer: prices + DVM + valuation + result-lag fundamentals all carry
    # real history from 2016-06, so the strategy is backtestable over that window (no snapshot gate).
    if cfg.data_source == "trendlyne":
        tl_feats = sorted(f for f in all_feats if f in _TL)
        # own-DVM + raw fundamentals (durability_own / valuation_own / roe / roa / opm / np_qtr_yoy).
        # Since iter-30 these join the screener history correctly, so they ARE backtestable — we no
        # longer hide them. Report them honestly so the card can't claim a clean run that won't trade.
        fund_feats = sorted(f for f in all_feats if f in _FUND)
        fund_in_filter = sorted(f for f in filter_feats if f in _FUND)
        fund_in_rank = sorted(f for f in rank_feats if f in _FUND)
        unknown = sorted(f for f in all_feats
                         if f not in _TL and f not in _FUND and _classify(f) == "unknown")
        sccov = fund.screener_coverage()
        # Concise, honest one-liner — no wall of caveats (owner feedback iter-30).
        summary = (f"Backtestable from {TL_HISTORY_FROM} — survivorship-free Trendlyne prices, "
                   f"point-in-time ₹500cr membership, split/bonus-adjusted incl. delisted names.")
        if fund_feats:
            summary += (f" Fundamentals {fund_feats} are screener-history-backed"
                        + (f" ({sccov['tickers']} names, {fund.PIT_LAG_DAYS}d-lagged)" if sccov.get("available") else "")
                        + ".")
        if unknown:
            summary += f" Unrecognized {unknown} will be skipped."
        return {
            "verdict": "backtestable", "backtestable_from": TL_HISTORY_FROM,
            "price_coverage": {"from": TL_HISTORY_FROM, "to": None},
            "fundamentals_snapshot": None, "screener_history": sccov,
            "fundamentals_in_filter": fund_in_filter, "fundamentals_in_rank": fund_in_rank,
            "unknown_features": unknown,
            "features": [{"name": f, "kind": "trendlyne" if f in _TL else "fundamental",
                          "used_in": [u for u, s in (("filter", filter_feats), ("rank", rank_feats)) if f in s],
                          "coverage_from": TL_HISTORY_FROM,
                          "source": "screener-history" if f in _FUND else "trendlyne-history"}
                         for f in (tl_feats + fund_feats)],
            "summary": summary,
        }

    cov = store.coverage_summary()
    price_from, price_to = cov.get("date_min"), cov.get("date_max")
    snaps = fund.snapshots()
    fund_from = snaps[0] if snaps else None
    sccov = fund.screener_coverage()
    hist_from = sccov["history_from"] if sccov.get("available") else None
    lag_txt = f"{fund.PIT_LAG_DAYS}d-lagged"

    def _hist_backed(f: str) -> bool:
        return f in _HIST_FUND and hist_from is not None

    # A fundamental's coverage starts at the screener history (if history-backed) else the snapshot.
    def _fund_cov(f: str):
        return hist_from if _hist_backed(f) else fund_from

    fund_in_filter = sorted(f for f in filter_feats if _classify(f) == "fundamental")
    fund_in_rank = sorted(f for f in rank_feats if _classify(f) == "fundamental")
    unknown = sorted(f for f in all_feats if _classify(f) == "unknown")
    # snapshot-only fundamental filters still gate the run to live; history-backed ones are backtestable.
    snap_only_filter = [f for f in fund_in_filter if not _hist_backed(f)]
    hist_filter = [f for f in fund_in_filter if _hist_backed(f)]

    features = []
    for f in sorted(all_feats):
        kind = _classify(f)
        used_in = [u for u, s in (("filter", filter_feats), ("rank", rank_feats)) if f in s]
        coverage_from = (price_from if kind == "price"
                         else (_fund_cov(f) if kind == "fundamental" else None))
        features.append({"name": f, "kind": kind, "used_in": used_in,
                         "coverage_from": coverage_from,
                         "source": ("screener-history" if _hist_backed(f) else "snapshot")
                         if kind == "fundamental" else None})

    if snap_only_filter and fund_from:
        verdict = "live-only"
        backtestable_from = fund_from
        tail = (f" (history-backed filter(s) {hist_filter} do have screener history from {hist_from})"
                if hist_filter else "")
        summary = (f"Live-only: snapshot-only fundamental filter(s) {snap_only_filter} are NaN before "
                   f"the {fund_from} snapshot, so a historical backtest holds nothing — run it on "
                   f"/signals.{tail}")
    elif snap_only_filter and not fund_from:
        verdict = "blocked"
        backtestable_from = None
        summary = (f"Blocked: fundamental filter(s) {snap_only_filter} need a snapshot, but none is "
                   f"loaded. Ingest a Trendlyne snapshot to run them live.")
    elif hist_filter:
        verdict = "backtestable"
        backtestable_from = hist_from
        summary = (f"Backtestable from {hist_from}: fundamental filter(s) {hist_filter} are backed by "
                   f"screener historical fundamentals ({sccov['tickers']} names, {lag_txt}). Before "
                   f"{hist_from} the screener history has no lagged value, so those names drop out.")
    elif fund_in_rank:
        verdict = "price-backtestable"
        backtestable_from = price_from
        hist_rank = [f for f in fund_in_rank if _hist_backed(f)]
        snap_rank = [f for f in fund_in_rank if not _hist_backed(f)]
        bits = []
        if hist_rank:
            bits.append(f"history-backed rank factor(s) {hist_rank} activate from {hist_from} "
                        f"(screener history, {lag_txt})")
        if snap_rank:
            bits.append(f"snapshot-only rank factor(s) {snap_rank} activate from the {fund_from} "
                        f"snapshot onward" if fund_from else
                        f"snapshot-only rank factor(s) {snap_rank} have no snapshot yet, so the blend "
                        f"uses price factors only")
        summary = "Backtestable over full price history; " + "; ".join(bits) + "."
    else:
        verdict = "fully-backtestable"
        backtestable_from = price_from
        summary = "Fully backtestable: all factors are price-derived over the loaded price history."

    if unknown:
        summary += f" Note: unrecognized feature(s) {unknown} will be skipped."

    return {
        "verdict": verdict,
        "backtestable_from": backtestable_from,
        "price_coverage": {"from": price_from, "to": price_to},
        "fundamentals_snapshot": fund_from,
        "screener_history": sccov,
        "fundamentals_in_filter": fund_in_filter,
        "fundamentals_in_rank": fund_in_rank,
        "unknown_features": unknown,
        "features": features,
        "summary": summary,
    }
