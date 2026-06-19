"""Indicator unit tests against known behavior / reference values."""
import numpy as np
import pandas as pd

from windfall.signals import adtv, atr, ema, roc, rsi, sma


def _series(vals):
    return pd.Series(vals, index=pd.bdate_range("2020-01-01", periods=len(vals)), dtype=float)


def test_sma_flat_series_equals_level():
    s = _series([100.0] * 30)
    assert abs(sma(s, 10).iloc[-1] - 100.0) < 1e-9


def test_sma_known_window():
    s = _series([1, 2, 3, 4, 5, 6])
    # SMA(3) of last three (4,5,6) = 5
    assert abs(sma(s, 3).iloc[-1] - 5.0) < 1e-9


def test_roc_known():
    s = _series([100, 110, 121])  # +10% each step; ROC(1) last = 10
    assert abs(roc(s, 1).iloc[-1] - 10.0) < 1e-6


def test_rsi_strict_uptrend_is_high():
    s = _series(np.arange(1, 60, dtype=float))
    assert rsi(s, 14).iloc[-1] >= 95.0


def test_rsi_strict_downtrend_is_low():
    s = _series(np.arange(60, 1, -1, dtype=float))
    assert rsi(s, 14).iloc[-1] <= 5.0


def test_ema_responds_faster_than_sma():
    s = _series(list(range(1, 40)))
    assert ema(s, 10).iloc[-1] > sma(s, 10).iloc[-1]  # rising series: EMA leads SMA


def test_atr_positive_with_range():
    n = 40
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = pd.Series(np.linspace(100, 120, n), index=idx)
    high = close + 2.0
    low = close - 2.0
    a = atr(high, low, close, 14).iloc[-1]
    assert a > 0


def test_adtv_is_price_times_volume_mean():
    n = 25
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = pd.Series([100.0] * n, index=idx)
    vol = pd.Series([1000.0] * n, index=idx)
    # mean(100*1000) = 100000
    assert abs(adtv(close, vol, 20).iloc[-1] - 100000.0) < 1e-6
