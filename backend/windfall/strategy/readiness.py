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
_SPECIAL = {"adtv_cr", "macd", "macd_signal", "macd_hist"}
_FUND = set(fund.NUMERIC_FIELDS) | {"pe_to_sector"}


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

    cov = store.coverage_summary()
    price_from, price_to = cov.get("date_min"), cov.get("date_max")
    snaps = fund.snapshots()
    fund_from = snaps[0] if snaps else None

    fund_in_filter = sorted(f for f in filter_feats if _classify(f) == "fundamental")
    fund_in_rank = sorted(f for f in rank_feats if _classify(f) == "fundamental")
    unknown = sorted(f for f in all_feats if _classify(f) == "unknown")

    features = []
    for f in sorted(all_feats):
        kind = _classify(f)
        used_in = [u for u, s in (("filter", filter_feats), ("rank", rank_feats)) if f in s]
        coverage_from = price_from if kind == "price" else (fund_from if kind == "fundamental" else None)
        features.append({"name": f, "kind": kind, "used_in": used_in, "coverage_from": coverage_from})

    if fund_in_filter and fund_from:
        verdict = "live-only"
        backtestable_from = fund_from
        summary = (f"Live-only: fundamental filter(s) {fund_in_filter} are NaN before the "
                   f"{fund_from} snapshot, so a historical backtest holds nothing — run it on "
                   f"/signals. Backtest history accrues as monthly snapshots accumulate.")
    elif fund_in_filter and not fund_from:
        verdict = "blocked"
        backtestable_from = None
        summary = (f"Blocked: fundamental filter(s) {fund_in_filter} need a snapshot, but none is "
                   f"loaded. Ingest a Trendlyne snapshot to run it live.")
    elif fund_in_rank:
        verdict = "price-backtestable"
        backtestable_from = price_from
        tail = (f"; the fundamental rank factor(s) {fund_in_rank} are blank-tolerant and activate "
                f"from the {fund_from} snapshot onward" if fund_from else
                f"; the fundamental rank factor(s) {fund_in_rank} have no snapshot yet, so the "
                f"blend uses price factors only")
        summary = f"Backtestable over full price history{tail}."
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
        "fundamentals_in_filter": fund_in_filter,
        "fundamentals_in_rank": fund_in_rank,
        "unknown_features": unknown,
        "features": features,
        "summary": summary,
    }
