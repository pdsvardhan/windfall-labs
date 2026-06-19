"""Golden-number tests for the metrics layer against hand-computed values."""
import numpy as np
import pandas as pd

from windfall.engine.metrics import compute_summary, drawdown_series


def test_cagr_on_a_doubling_over_one_year():
    idx = pd.bdate_range("2020-01-01", periods=261)  # ~1 trading year
    nav = pd.Series(np.linspace(100.0, 200.0, len(idx)), index=idx)
    s = compute_summary(nav, trades=[], benchmark=None, years=1.0, annual_turnover=0.0, exposure=1.0)
    assert abs(s.total_return - 1.0) < 1e-6          # 100 -> 200 = +100%
    assert abs(s.cagr - 1.0) < 0.02                  # ~1 year, ~100% CAGR


def test_max_drawdown_is_exact():
    nav = pd.Series([100, 120, 60, 90, 150],
                    index=pd.bdate_range("2021-01-01", periods=5))
    dd = drawdown_series(nav)
    # peak 120 -> trough 60 = -50%
    assert abs(dd.min() - (-0.5)) < 1e-9


def test_win_rate_and_profit_factor_from_trades():
    trades = [
        {"return_pct": 0.10, "exit": 1, "holding_days": 5},
        {"return_pct": 0.20, "exit": 1, "holding_days": 5},
        {"return_pct": -0.10, "exit": 1, "holding_days": 5},
    ]
    nav = pd.Series([100, 110], index=pd.bdate_range("2021-01-01", periods=2))
    s = compute_summary(nav, trades, benchmark=None, years=1.0, annual_turnover=1.0, exposure=1.0)
    assert s.n_trades == 3
    assert abs(s.win_rate - (2 / 3)) < 1e-3  # win_rate is rounded to 4dp
    # gross win 0.30 / gross loss 0.10 = 3.0
    assert abs(s.profit_factor - 3.0) < 1e-6
