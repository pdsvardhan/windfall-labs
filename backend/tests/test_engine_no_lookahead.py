"""The anti-gaslight rails for the engine: determinism, no look-ahead, next-open fills."""
import pandas as pd

from windfall.data import store
from windfall.engine.backtest import run_backtest

BASE = {
    "name": "test_strat",
    "universe": {"index": "nifty500", "filters": []},
    "entry_filters": ["close > sma50"],
    "rank_by": "roc21", "rank_order": "desc",
    "n_holdings": 3, "weighting": "equal", "rebalance": "weekly", "entry_fill": "next_open",
    "stop_loss": {"type": "none"}, "take_profit": {"type": "none"},
    "costs_bps": {"brokerage": 3, "stt": 10, "slippage": 15},
    "start": "2018-06-01", "end": "2020-12-31", "benchmark": "NIFTY500",
}


def test_determinism_identical_runs():
    a = run_backtest(dict(BASE))
    b = run_backtest(dict(BASE))
    assert a.config_hash == b.config_hash
    assert a.equity_curve == b.equity_curve
    assert [t.model_dump() for t in a.trades] == [t.model_dump() for t in b.trades]


def test_no_lookahead_truncation_invariant():
    """Truncating the future must not change the past. If the engine peeked ahead, NAV before the
    truncation boundary would differ between the full run and the truncated run."""
    full = run_backtest({**BASE, "end": "2020-12-31"})
    mid = run_backtest({**BASE, "end": "2020-06-30"})
    cutoff = pd.Timestamp("2020-03-31")  # safely before the truncation boundary

    full_nav = {d: v for d, v in full.equity_curve if pd.Timestamp(d) <= cutoff}
    mid_nav = {d: v for d, v in mid.equity_curve if pd.Timestamp(d) <= cutoff}
    assert full_nav.keys() == mid_nav.keys() and len(full_nav) > 0
    for d in full_nav:
        assert abs(full_nav[d] - mid_nav[d]) < 1e-6, f"past NAV changed at {d} — look-ahead leak"


def test_fills_at_next_open_not_decision_close():
    res = run_backtest(dict(BASE))
    assert res.trades, "expected the strategy to trade on synthetic data"
    open_panel = store.price_panel("open", start=BASE["start"], end=BASE["end"], adjusted=True)
    checked = 0
    for t in res.trades[:10]:
        d = pd.Timestamp(t.entry_date)
        if d in open_panel.index and t.ticker in open_panel.columns:
            expected_open = float(open_panel.loc[d, t.ticker])
            assert abs(t.entry - expected_open) < 0.05 * max(expected_open, 1.0), \
                "entry price should equal the adjusted open on the entry date (next-open fill)"
            checked += 1
    assert checked > 0
