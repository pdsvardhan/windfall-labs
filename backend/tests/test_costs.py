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


def test_cost_mult_reduces_returns_strictly():
    """The REAL cost lever is cost_mult over the NSE delivery schedule (adr-020). The old version
    of this test gridded the inert costs_bps field and asserted <=, which two EQUAL runs satisfy —
    it was green while proving nothing (iter-23 #637). Strict inequality on a trading book."""
    free = run_backtest(dict(BASE), cost_mult=0.0)
    costly = run_backtest(dict(BASE), cost_mult=1.0)
    assert costly.summary.n_trades > 0
    assert costly.summary.total_return < free.summary.total_return


def test_costs_bps_is_inert_and_warned():
    """costs_bps survives in the schema only for stored-config compat; it must change NOTHING,
    and deliberately setting it must draw the deprecation warning (adr-020, iter-23 #637)."""
    a = run_backtest({**BASE, "costs_bps": {"brokerage": 0, "stt": 0, "slippage": 0}})
    b = run_backtest({**BASE, "costs_bps": {"brokerage": 99, "stt": 99, "slippage": 99}})
    assert a.summary.total_return == b.summary.total_return
    assert any("costs_bps is inert" in w for w in a.warnings)
    assert any("costs_bps is inert" in w for w in b.warnings)


def test_default_costs_bps_not_warned():
    res = run_backtest(dict(BASE))
    assert not any("costs_bps is inert" in w for w in res.warnings)


def test_turnover_reported_and_nonnegative():
    res = run_backtest(dict(BASE))
    assert res.summary.annual_turnover >= 0.0
    # a weekly rotation strategy should actually turn the book over
    assert res.summary.n_trades > 0


def test_exposure_within_bounds():
    res = run_backtest(dict(BASE))
    assert 0.0 <= res.summary.exposure <= 1.5  # allow slight >1 from intraday marking quirks
