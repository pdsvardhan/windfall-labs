"""Regime filter + invest_fully behavior."""
from windfall.engine.backtest import run_backtest

BASE = {
    "name": "regime_test",
    "universe": {"index": "nifty500", "filters": []},
    "entry_filters": ["close > sma50"],
    "rank_by": "roc21", "rank_order": "desc",
    "n_holdings": 3, "weighting": "equal", "rebalance": "weekly", "entry_fill": "next_open",
    "stop_loss": {"type": "none"}, "take_profit": {"type": "none"},
    "start": "2018-06-01", "end": "2020-12-31", "benchmark": "NIFTY500",
}


def test_regime_filter_only_reduces_exposure():
    plain = run_backtest(dict(BASE))
    regime = run_backtest({**BASE, "regime_filter": {"enabled": True, "ma_period": 50,
                                                     "mode": "binary", "below_exposure": 0.0}})
    # A regime gate can only de-risk; it must never increase average exposure.
    assert regime.summary.exposure <= plain.summary.exposure + 1e-9


def test_regime_filter_is_deterministic():
    a = run_backtest({**BASE, "regime_filter": {"enabled": True, "ma_period": 50}})
    b = run_backtest({**BASE, "regime_filter": {"enabled": True, "ma_period": 50}})
    assert a.config_hash == b.config_hash
    assert a.equity_curve == b.equity_curve


def test_invest_fully_runs_and_is_finite():
    res = run_backtest({**BASE, "invest_fully": True})
    assert res.summary.n_trades > 0
    assert 0.0 <= res.summary.exposure <= 1.5
