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
from ..data import store
from ..data.universe import benchmark_ticker
from .safe_eval import SafeEvalError, feature_names, safe_eval
from .schema import StrategyConfig

_PARAM = re.compile(r"^(sma|ema|roc|rsi|atr|adx|adtv|vol_avg|dist_high|rel_strength)(\d+)$")
_BASE = {"close", "open", "high", "low", "volume", "adj_close", "price"}
_SPECIAL = {"adtv_cr", "macd", "macd_signal", "macd_hist"}


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
        cache[name] = df
        return df

    def eval_expr(expr: str) -> pd.DataFrame | None:
        ns: dict[str, pd.DataFrame] = {}
        for tok in feature_names(expr):
            if not (tok in _BASE or tok in _SPECIAL or _PARAM.match(tok)):
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

    # Rank score.
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
