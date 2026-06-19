"""Resolve a declarative StrategyConfig into the concrete panels the engine consumes.

Filter/rank expressions reference named features (close, sma50, roc21, rsi14, adtv_cr, ...).
We build only the features that appear in the config, then evaluate each expression columnwise
into a boolean (filters) or numeric (rank) wide panel. NaN never passes a filter.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import signals as ind
from ..data import fundamentals as fund
from ..data import store
from ..scores import own_dvm as own
from ..data.universe import benchmark_ticker
from .safe_eval import SafeEvalError, feature_names, safe_eval
from .schema import StrategyConfig

_PARAM = re.compile(r"^(sma|ema|roc|rsi|atr|adx|adtv|vol_avg|dist_high|rel_strength)(\d+)$")
_BASE = {"close", "open", "high", "low", "volume", "adj_close", "price"}
_SPECIAL = {"adtv_cr", "macd", "macd_signal", "macd_hist"}
# Fundamental features from the Trendlyne snapshot (point-in-time; NaN before the snapshot date).
_FUND = set(fund.NUMERIC_FIELDS) | {"pe_to_sector"}
# Our own reproducible scores (scores/own_dvm.py). momentum_own is price-only (full history);
# durability_own / valuation_own derive from fundamentals (snapshot-gated).
_OWN = {"momentum_own", "durability_own", "valuation_own"}
# Fundamentals that now gain real history from the screener store (durability inputs + durability_own).
# These are 120d-lagged point-in-time over ~2006->present, not snapshot-gated.
_HIST_FUND = set(fund.SCREENER_HISTORY_FIELDS) | {"durability_own"}


@dataclass
class ResolvedStrategy:
    config: StrategyConfig
    tickers: list[str]
    entry_mask: pd.DataFrame          # date x ticker, bool — passes all entry+universe filters
    rank_score: pd.DataFrame          # date x ticker, numeric — ranking metric
    open_adj: pd.DataFrame            # adjusted open (fills)
    close_adj: pd.DataFrame           # adjusted close (marking)
    high_adj: pd.DataFrame
    low_adj: pd.DataFrame
    atr_stop: pd.DataFrame | None     # ATR panel for stop sizing, if needed
    ret_vol: pd.DataFrame             # rolling return volatility (inverse-vol weighting)
    adtv_value: pd.DataFrame          # ADTV in rupees (sizing cap)
    sectors: dict[str, str]
    benchmark: pd.Series
    warnings: list[str] = field(default_factory=list)


def _trading_dates(close: pd.DataFrame) -> pd.DatetimeIndex:
    return close.index


def _percentile_blend(factors, mask, eval_expr, idx, cols, warnings) -> pd.DataFrame | None:
    """Cross-sectional percentile blend over the eligible set, per rebalance date.

    For each factor: evaluate -> restrict to eligible cells (mask) -> percentile-rank across
    tickers within each date (inverting for 'asc' factors) -> multiply by weight. Sum the
    (pct * weight) contributions and divide by the per-cell sum of weights that actually had a
    value, so a factor that is NaN for a name (e.g. a fundamental before its snapshot) drops out
    and the remaining weights renormalize. Returns a date x ticker score panel (higher = better),
    NaN where ineligible or where no factor had data.
    """
    blended: pd.DataFrame | None = None   # running sum of pct*weight over available factors
    wsum: pd.DataFrame | None = None      # running sum of weights over available factors (per cell)
    for rf in factors:
        panel = eval_expr(rf.factor)
        if panel is None:
            warnings.append(f"rank_blend factor '{rf.factor}' unresolved — dropped from blend")
            continue
        vals = panel.reindex(index=idx, columns=cols).where(mask)   # NaN where not eligible
        if rf.order == "asc":
            vals = -vals
        pct = vals.rank(axis=1, pct=True)                           # percentile within eligible non-NaN
        contrib = (pct * rf.weight).fillna(0.0)
        present = pct.notna().astype(float) * rf.weight
        blended = contrib if blended is None else blended.add(contrib)
        wsum = present if wsum is None else wsum.add(present)
        if float(pct.notna().to_numpy().mean()) == 0.0:
            warnings.append(
                f"rank_blend factor '{rf.factor}' has no data in this window — excluded from the "
                f"blend here (e.g. a fundamental before its first snapshot).")
    if blended is None or wsum is None:
        return None
    return blended.divide(wsum.replace(0.0, np.nan)).where(mask)    # weighted-mean percentile


def resolve(cfg: StrategyConfig) -> ResolvedStrategy:
    index = cfg.universe.index
    members = store.universe_tickers(index)
    have = set(store.available_tickers())
    tickers = [t for t in members if t in have] or [t for t in have if t.endswith(".NS")]

    # Adjusted panels for the trading universe.
    close = store.price_panel("close", tickers, cfg.start, cfg.end, adjusted=True)
    open_ = store.price_panel("open", tickers, cfg.start, cfg.end, adjusted=True)
    high = store.price_panel("high", tickers, cfg.start, cfg.end, adjusted=True)
    low = store.price_panel("low", tickers, cfg.start, cfg.end, adjusted=True)
    if close.empty:
        raise ValueError("No price data for the resolved universe — load data first.")
    tickers = list(close.columns)

    # Raw panels for traded-value (ADTV uses real, unadjusted price * volume).
    raw_close = store.price_panel("close", tickers, cfg.start, cfg.end, adjusted=False)
    raw_vol = store.price_panel("volume", tickers, cfg.start, cfg.end, adjusted=False)

    warnings: list[str] = []
    bt = benchmark_ticker(cfg.benchmark)
    bench_panel = store.price_panel("close", [bt], cfg.start, cfg.end, adjusted=True)
    if not bench_panel.empty and bt in bench_panel.columns:
        benchmark = bench_panel[bt]
    else:
        benchmark = close.mean(axis=1)
        warnings.append(
            f"benchmark '{cfg.benchmark}' ({bt}) not loaded — falling back to an equal-weight "
            f"universe average; benchmark_cagr/active_return are NOT the real index.")

    cache: dict[str, pd.DataFrame] = {}

    def feat(name: str) -> pd.DataFrame:
        if name in cache:
            return cache[name]
        df: pd.DataFrame
        if name in ("close", "adj_close", "price"):
            df = close
        elif name == "open":
            df = open_
        elif name == "high":
            df = high
        elif name == "low":
            df = low
        elif name == "volume":
            df = raw_vol
        elif name == "adtv_cr":
            df = ind.adtv(raw_close, raw_vol, 20) / 1e7
        elif name == "macd":
            df = ind.macd(close)[0]
        elif name == "macd_signal":
            df = ind.macd(close)[1]
        elif name == "macd_hist":
            df = ind.macd(close)[2]
        elif name == "pe_to_sector":
            df = feat("pe") / feat("sector_pe").replace(0.0, np.nan)
        elif name == "momentum_own":
            df = own.momentum_own(feat("roc63"), feat("roc126"), feat("roc252"),
                                  feat("rsi14"), feat("rel_strength126"))
        elif name == "durability_own":
            df = own.durability_own(feat("roe"), feat("roa"), feat("piotroski"),
                                    feat("opm"), feat("np_qtr_yoy"), feat("promoter_pledge"))
        elif name == "valuation_own":
            df = own.valuation_own(feat("pe"), feat("pb"), feat("pe_to_sector"))
        elif name in fund.NUMERIC_FIELDS:
            snap = fund.fundamental_panel(name, close.index, tickers)
            # durability inputs (roe/roa/opm/np_qtr_yoy) gain real history from the screener store.
            # combine_first keeps the snapshot where it has a value (from its date forward) and uses
            # the 120d-lagged screener history for the past — present from snapshot, history from
            # screener, with no look-ahead. Other fundamentals (None) stay snapshot-only.
            hist = fund.screener_history_panel(name, close.index, tickers)
            df = snap if hist is None else snap.combine_first(hist)
        else:
            m = _PARAM.match(name)
            if not m:
                raise KeyError(name)
            kind, n_s = m.group(1), int(m.group(2))
            if kind == "sma":
                df = ind.sma(close, n_s)
            elif kind == "ema":
                df = ind.ema(close, n_s)
            elif kind == "roc":
                df = ind.roc(close, n_s)
            elif kind == "rsi":
                df = ind.rsi(close, n_s)
            elif kind == "atr":
                df = ind.atr(high, low, close, n_s)
            elif kind == "adx":
                df = ind.adx(high, low, close, n_s)
            elif kind == "adtv":
                df = ind.adtv(raw_close, raw_vol, n_s)
            elif kind == "vol_avg":
                df = ind.volume_avg(raw_vol, n_s)
            elif kind == "dist_high":
                df = ind.dist_from_high(close, n_s)
            elif kind == "rel_strength":
                df = ind.relative_strength(close, benchmark, n_s)
            else:  # pragma: no cover
                raise KeyError(name)
        if df is None:  # a score with no usable inputs -> an all-NaN panel (never passes a filter)
            df = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
        cache[name] = df
        return df

    def eval_expr(expr: str) -> pd.DataFrame | None:
        ns: dict[str, pd.DataFrame] = {}
        for tok in feature_names(expr):
            if not (tok in _BASE or tok in _SPECIAL or tok in _FUND or tok in _OWN
                    or _PARAM.match(tok)):
                warnings.append(f"unknown feature '{tok}' in '{expr}' — filter skipped")
                return None
            ns[tok] = feat(tok)
        try:
            return safe_eval(expr, ns)
        except SafeEvalError as exc:
            warnings.append(f"rejected expression '{expr}': {exc} — filter skipped")
            return None
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"could not evaluate '{expr}': {exc!r} — skipped")
            return None

    # Universe + entry filters → combined boolean mask.
    mask = pd.DataFrame(True, index=close.index, columns=close.columns)
    for expr in list(cfg.universe.filters) + list(cfg.entry_filters):
        res = eval_expr(expr)
        if res is None:
            continue
        res = res.reindex(index=close.index, columns=close.columns)
        mask &= res.fillna(False).astype(bool)

    # Sector exclusion (e.g. the methodology's "exclude Banking & Finance").
    if cfg.universe.exclude_sectors:
        sect = fund.fundamentals_sector_map()
        nse_sect = store.sector_map(index)
        excl = [s.strip().lower() for s in cfg.universe.exclude_sectors]
        drop = [t for t in close.columns
                if any(e in (sect.get(t) or nse_sect.get(t) or "").lower() for e in excl)]
        if drop:
            mask[drop] = False
            warnings.append(f"excluded {len(drop)} names in sectors {cfg.universe.exclude_sectors}")

    # Honesty: which fundamentals are screener-history-backed (120d-lagged, real history) vs
    # snapshot-only (NaN before the single Trendlyne snapshot).
    blend_exprs = [rf.factor for rf in cfg.rank_blend]
    all_exprs = (list(cfg.universe.filters) + list(cfg.entry_filters) + blend_exprs
                 + ([cfg.rank_by] if not cfg.rank_blend else []))
    used_fund = {t for e in all_exprs for t in feature_names(e)
                 if t in _FUND or t in ("durability_own", "valuation_own")}
    if used_fund:
        sccov = fund.screener_coverage()
        hist_used = sorted(t for t in used_fund if t in _HIST_FUND)
        snap_used = sorted(t for t in used_fund if t not in _HIST_FUND)
        if hist_used and sccov.get("available"):
            warnings.append(
                f"durability fundamentals {hist_used} are screener-history-backed "
                f"({sccov['tickers']} names from {sccov['history_from']}, {fund.PIT_LAG_DAYS}d-lagged); "
                f"the live snapshot governs the present, and piotroski/pledge remain snapshot-only.")
        snaps = fund.snapshots()
        if snap_used and snaps:
            warnings.append(
                f"snapshot-only fundamentals {snap_used} come from Trendlyne snapshots {snaps} and are "
                f"NaN before the first snapshot, so they apply to live signals / dates on-or-after the "
                f"snapshot, not historical backtests.")
        elif snap_used:
            warnings.append(
                f"snapshot-only fundamentals {snap_used} but no fundamentals snapshot is loaded.")

    # Rank score — a single expression, or a multi-factor cross-sectional percentile blend.
    if cfg.rank_blend:
        rank = _percentile_blend(cfg.rank_blend, mask, eval_expr,
                                 close.index, close.columns, warnings)
        if rank is None:
            warnings.append("rank_blend produced no usable factors — defaulting to roc21")
            rank = feat("roc21").reindex(index=close.index, columns=close.columns)
    else:
        rank = eval_expr(cfg.rank_by)
        if rank is None:
            warnings.append(f"rank_by '{cfg.rank_by}' unresolved — defaulting to roc21")
            rank = feat("roc21")
        rank = rank.reindex(index=close.index, columns=close.columns)

    atr_stop = None
    if cfg.stop_loss.type in ("atr", "trailing"):
        atr_stop = ind.atr(high, low, close, cfg.stop_loss.atr_period)

    ret = close.pct_change()
    ret_vol = ret.rolling(20, min_periods=10).std()
    adtv_value = ind.adtv(raw_close, raw_vol, 20)

    return ResolvedStrategy(
        config=cfg, tickers=tickers, entry_mask=mask, rank_score=rank,
        open_adj=open_, close_adj=close, high_adj=high, low_adj=low,
        atr_stop=atr_stop, ret_vol=ret_vol, adtv_value=adtv_value,
        sectors=store.sector_map(index), benchmark=benchmark, warnings=warnings,
    )
