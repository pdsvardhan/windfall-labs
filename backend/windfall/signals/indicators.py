"""Vectorized technical indicators.

Every function accepts either a pandas Series (single ticker) or a wide DataFrame
(index=date, columns=ticker) and returns the same shape, computed columnwise with no Python
loops over tickers. Wilder-style smoothing uses an EWM with alpha = 1/n.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

Frame = pd.Series | pd.DataFrame


def sma(x: Frame, n: int) -> Frame:
    return x.rolling(n, min_periods=n).mean()


def ema(x: Frame, n: int) -> Frame:
    return x.ewm(span=n, adjust=False, min_periods=n).mean()


def roc(x: Frame, n: int) -> Frame:
    """Rate of change in percent over n periods."""
    return (x / x.shift(n) - 1.0) * 100.0


def rsi(close: Frame, n: int = 14) -> Frame:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    return out.fillna(100.0).where(close.notna())


def _true_range(high: Frame, low: Frame, close: Frame) -> Frame:
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    if isinstance(high, pd.DataFrame):
        return pd.DataFrame(
            np.maximum.reduce([tr1.values, tr2.values, tr3.values]),
            index=high.index, columns=high.columns,
        )
    return pd.Series(np.maximum.reduce([tr1.values, tr2.values, tr3.values]), index=high.index)


def atr(high: Frame, low: Frame, close: Frame, n: int = 14) -> Frame:
    tr = _true_range(high, low, close)
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def adx(high: Frame, low: Frame, close: Frame, n: int = 14) -> Frame:
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    tr = _true_range(high, low, close)
    atr_n = tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean() / atr_n
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean() / atr_n
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return dx.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def macd(close: Frame, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def rolling_high(x: Frame, n: int) -> Frame:
    return x.rolling(n, min_periods=1).max()


def rolling_low(x: Frame, n: int) -> Frame:
    return x.rolling(n, min_periods=1).min()


def dist_from_high(close: Frame, n: int = 252) -> Frame:
    """Distance below the rolling n-day high, as a fraction (0 = at the high, -0.1 = 10% below)."""
    return close / rolling_high(close, n) - 1.0


def volume_avg(volume: Frame, n: int = 20) -> Frame:
    return volume.rolling(n, min_periods=1).mean()


def adtv(close: Frame, volume: Frame, n: int = 20) -> Frame:
    """Average daily traded value over n days = mean(close * volume)."""
    return (close * volume).rolling(n, min_periods=1).mean()


def relative_strength(close: pd.DataFrame, benchmark: pd.Series, n: int = 63) -> pd.DataFrame:
    """Ratio of each ticker's n-day return to the benchmark's n-day return (>1 = outperforming)."""
    stock_ret = close / close.shift(n)
    bench_ret = benchmark / benchmark.shift(n)
    bench_ret = bench_ret.reindex(close.index).ffill()
    return stock_ret.div(bench_ret, axis=0)
