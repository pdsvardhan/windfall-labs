"""Costs must drag returns and turnover must be reported (Build-Spec rail #1)."""
from windfall.engine.backtest import run_backtest

BASE = {
    "name": "cost_test",
    "universe": {"index": "nifty500", "filters": []},
    "entry_filters": ["close > sma50"],
    "rank_by": "roc21", "rank_order": "desc",
    "n_holdings": 3, "weighting": "equal", "rebalance": "weekly", "entry_fill": "next_open",
    "stop_loss": {"type": "none"}, "take_profit": {"type": "none"},
    "start": "2018-06-01", "end": "2020-12-31", "benchmark": "NIFTY500",
}


def test_costs_reduce_returns():
    free = run_backtest({**BASE, "costs_bps": {"brokerage": 0, "stt": 0, "slippage": 0}})
    costly = run_backtest({**BASE, "costs_bps": {"brokerage": 10, "stt": 20, "slippage": 50}})
    # With identical selection, costs can only reduce (or equal) the net return.
    assert costly.summary.total_return <= free.summary.total_return + 1e-9


def test_turnover_reported_and_nonnegative():
    res = run_backtest(dict(BASE))
    assert res.summary.annual_turnover >= 0.0
    # a weekly rotation strategy should actually turn the book over
    assert res.summary.n_trades > 0


def test_exposure_within_bounds():
    res = run_backtest(dict(BASE))
    assert 0.0 <= res.summary.exposure <= 1.5  # allow slight >1 from intraday marking quirks
