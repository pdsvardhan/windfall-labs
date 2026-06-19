"""Performance metrics computed from a NAV series and a trade log."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .results import Summary

TRADING_DAYS = 252
# Below this exposure (fraction of book deployed) a run is treated as "sat in cash",
# so active_return vs the benchmark is suppressed (not comparable).
MIN_EXPOSURE_FOR_ACTIVE_RETURN = 0.01


def _cagr(nav: pd.Series, years: float) -> float:
    if len(nav) < 2 or years <= 0 or nav.iloc[0] <= 0:
        return 0.0
    return float((nav.iloc[-1] / nav.iloc[0]) ** (1.0 / years) - 1.0)


def drawdown_series(nav: pd.Series) -> pd.Series:
    return nav / nav.cummax() - 1.0


def monthly_returns(nav: pd.Series) -> list[list]:
    if nav.empty:
        return []
    m = nav.resample("ME").last()
    rets = m.pct_change().dropna()
    return [[idx.strftime("%Y-%m"), round(float(v), 6)] for idx, v in rets.items()]


def compute_summary(
    nav: pd.Series, trades: list[dict], benchmark: pd.Series | None,
    years: float, annual_turnover: float, exposure: float,
) -> Summary:
    s = Summary()
    if nav.empty or len(nav) < 2:
        return s
    ret = nav.pct_change().dropna()
    s.cagr = round(_cagr(nav, years), 6)
    s.total_return = round(float(nav.iloc[-1] / nav.iloc[0] - 1.0), 6)
    std = float(ret.std())
    s.volatility = round(std * np.sqrt(TRADING_DAYS), 6)
    s.sharpe = round(float(ret.mean() / std * np.sqrt(TRADING_DAYS)), 4) if std > 0 else 0.0
    downside = ret[ret < 0].std()
    s.sortino = round(float(ret.mean() / downside * np.sqrt(TRADING_DAYS)), 4) \
        if downside and downside > 0 else 0.0

    dd = drawdown_series(nav)
    s.max_drawdown = round(float(dd.min()), 6)
    trough = dd.idxmin()
    peak = nav.loc[:trough].idxmax() if trough in nav.index else nav.index[0]
    s.max_dd_dates = [str(pd.Timestamp(peak).date()), str(pd.Timestamp(trough).date())]

    closed = [t for t in trades if t.get("exit") is not None]
    s.n_trades = len(closed)
    if closed:
        rets = np.array([t["return_pct"] for t in closed], dtype=float)
        wins = rets[rets > 0]
        losses = rets[rets <= 0]
        s.win_rate = round(float(len(wins) / len(rets)), 4)
        s.avg_win = round(float(wins.mean()), 6) if len(wins) else 0.0
        s.avg_loss = round(float(losses.mean()), 6) if len(losses) else 0.0
        gross_win = float(wins.sum())
        gross_loss = abs(float(losses.sum()))
        s.profit_factor = round(gross_win / gross_loss, 4) if gross_loss > 0 else 0.0
        s.avg_holding_days = round(float(np.mean([t.get("holding_days", 0) for t in closed])), 2)

    s.annual_turnover = round(float(annual_turnover), 4)
    s.exposure = round(float(exposure), 4)

    if benchmark is not None and not benchmark.empty:
        b = benchmark.reindex(nav.index).ffill().dropna()
        if len(b) >= 2 and b.iloc[0] > 0:
            s.benchmark_cagr = round(_cagr(b, years), 6)
            # Only report active_return when the strategy actually took exposure. A run that
            # made 0 trades (or sat ~entirely in cash) shows a spuriously positive active_return
            # whenever the index fell — it didn't outperform, it just wasn't invested. Suppress
            # it with a reason instead of reporting a misleading number.
            if s.n_trades == 0 or s.exposure < MIN_EXPOSURE_FOR_ACTIVE_RETURN:
                s.active_return = None
                s.active_return_note = "no exposure (held cash) — not comparable to benchmark"
            else:
                s.active_return = round(s.cagr - s.benchmark_cagr, 6)
    return s
