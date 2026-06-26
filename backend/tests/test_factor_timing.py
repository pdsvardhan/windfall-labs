"""Factor-timing overlay (self-timing on the strategy's own equity) + weekly de-risk check.

The overlay must (a) be deterministic, (b) only ever REDUCE exposure, (c) never leak look-ahead
(truncating the future cannot change the past — the gate reads only lagged, already-recorded NAV),
and (d) actually go defensive when the strategy's own equity falls below its MA.
"""
import pandas as pd

from windfall.engine.backtest import run_backtest
from windfall.walkforward import walk_forward

BASE = {
    "name": "factor_timing_test",
    "universe": {"index": "nifty500", "filters": []},
    "entry_filters": ["close > sma50"],
    "rank_by": "roc21", "rank_order": "desc",
    "n_holdings": 3, "weighting": "equal", "rebalance": "monthly", "entry_fill": "next_open",
    "stop_loss": {"type": "none"}, "take_profit": {"type": "none"},
    "start": "2018-06-01", "end": "2020-12-31", "benchmark": "NIFTY500",
}


def test_factor_timing_only_reduces_exposure():
    plain = run_backtest(dict(BASE))
    timed = run_backtest({**BASE, "factor_timing": {"enabled": True, "ma_period": 20,
                                                    "mode": "binary", "below_exposure": 0.0}})
    # Self-timing is a risk control: it can stand in cash but never lever up.
    assert timed.summary.exposure <= plain.summary.exposure + 1e-9


def test_factor_timing_is_deterministic():
    a = run_backtest({**BASE, "factor_timing": {"enabled": True, "ma_period": 20}})
    b = run_backtest({**BASE, "factor_timing": {"enabled": True, "ma_period": 20}})
    assert a.config_hash == b.config_hash
    assert a.equity_curve == b.equity_curve
    assert [t.model_dump() for t in a.trades] == [t.model_dump() for t in b.trades]


def test_factor_timing_no_lookahead_truncation_invariant():
    """With the overlay ON, truncating the future must still not change the past — the gate uses
    only NAV recorded through (today - lag_days), so past NAV is independent of future bars."""
    cfg = {**BASE, "factor_timing": {"enabled": True, "ma_period": 20, "lag_days": 1}}
    full = run_backtest({**cfg, "end": "2020-12-31"})
    mid = run_backtest({**cfg, "end": "2020-06-30"})
    cutoff = pd.Timestamp("2020-03-31")
    full_nav = {d: v for d, v in full.equity_curve if pd.Timestamp(d) <= cutoff}
    mid_nav = {d: v for d, v in mid.equity_curve if pd.Timestamp(d) <= cutoff}
    assert full_nav.keys() == mid_nav.keys() and len(full_nav) > 0
    for d in full_nav:
        assert abs(full_nav[d] - mid_nav[d]) < 1e-6, f"past NAV changed at {d} — look-ahead leak"


def test_factor_timing_can_go_defensive():
    """A short MA makes the gate trip on the first drawdown; the timed run must spend at least some
    time below full exposure vs a plain run that is always trying to be invested."""
    plain = run_backtest({**BASE, "invest_fully": True})
    timed = run_backtest({**BASE, "invest_fully": True,
                          "factor_timing": {"enabled": True, "ma_period": 10, "mode": "binary"}})
    # Over a window containing the 2020 COVID crash, a 10-day self-timing gate must de-risk somewhere.
    assert timed.summary.exposure < plain.summary.exposure - 1e-6


def test_weekly_check_does_not_increase_exposure():
    """Enabling the weekly de-risk check can only pull exposure down vs the rebalance-only gate."""
    rebal_only = run_backtest({**BASE, "factor_timing": {"enabled": True, "ma_period": 20,
                                                         "check_weekly": False}})
    weekly = run_backtest({**BASE, "factor_timing": {"enabled": True, "ma_period": 20,
                                                     "check_weekly": True}})
    assert weekly.summary.exposure <= rebal_only.summary.exposure + 1e-9


def test_walkforward_sweeps_factor_timing_ma_period():
    """The MA-lookback is a degree of freedom — walk_forward must be able to optimize it in-sample
    and test it out-of-sample (dotted-path override), so we can tell a robust MA from a curve-fit one."""
    base = {**BASE, "factor_timing": {"enabled": True, "ma_period": 30}}
    wf = walk_forward(base, {"factor_timing.ma_period": [20, 40]}, metric="sharpe",
                      is_years=1.0, oos_years=0.5)
    assert wf["n_windows"] >= 1
    assert wf["verdict"] in {"robust", "likely-curve-fit", "inconclusive"}
    for w in wf["windows"]:
        # the optimizer must have applied the dotted path and picked a real grid value
        assert w["best_overrides"].get("factor_timing.ma_period") in (20, 40)


def test_reengage_weekly_requires_check_weekly():
    """reengage_weekly without check_weekly is a config error (can't re-engage on a cadence you
    don't evaluate)."""
    import pytest
    with pytest.raises(Exception):
        run_backtest({**BASE, "factor_timing": {"enabled": True, "reengage_weekly": True,
                                                 "check_weekly": False}})


def test_reengage_weekly_holds_more_exposure_than_derisk_only():
    """Bidirectional weekly re-engagement re-enters after de-risking, so it must hold at least as
    much average exposure as the de-risk-only weekly check (iter-17 vs iter-16 behavior)."""
    derisk = run_backtest({**BASE, "factor_timing": {"enabled": True, "ma_period": 20,
                                                     "check_weekly": True}})
    reengage = run_backtest({**BASE, "factor_timing": {"enabled": True, "ma_period": 20,
                                                       "check_weekly": True, "reengage_weekly": True}})
    assert reengage.summary.exposure >= derisk.summary.exposure - 1e-9


def test_reengage_weekly_no_lookahead_truncation_invariant():
    """Re-engagement is driven by the lagged reference curve + past monthly selections only, so
    truncating the future must not change the past."""
    cfg = {**BASE, "factor_timing": {"enabled": True, "ma_period": 20, "lag_days": 1,
                                      "check_weekly": True, "reengage_weekly": True}}
    full = run_backtest({**cfg, "end": "2020-12-31"})
    mid = run_backtest({**cfg, "end": "2020-06-30"})
    cutoff = pd.Timestamp("2020-03-31")
    full_nav = {d: v for d, v in full.equity_curve if pd.Timestamp(d) <= cutoff}
    mid_nav = {d: v for d, v in mid.equity_curve if pd.Timestamp(d) <= cutoff}
    assert full_nav.keys() == mid_nav.keys() and len(full_nav) > 0
    for d in full_nav:
        assert abs(full_nav[d] - mid_nav[d]) < 1e-6, f"past NAV changed at {d} — look-ahead leak"


def test_reengage_weekly_is_deterministic():
    a = run_backtest({**BASE, "factor_timing": {"enabled": True, "ma_period": 20,
                                                "check_weekly": True, "reengage_weekly": True}})
    b = run_backtest({**BASE, "factor_timing": {"enabled": True, "ma_period": 20,
                                                "check_weekly": True, "reengage_weekly": True}})
    assert a.equity_curve == b.equity_curve
    assert [t.model_dump() for t in a.trades] == [t.model_dump() for t in b.trades]


def test_disabled_factor_timing_is_a_noop():
    """An explicitly-disabled overlay must reproduce the plain run byte-for-byte (no silent drift)."""
    plain = run_backtest(dict(BASE))
    off = run_backtest({**BASE, "factor_timing": {"enabled": False}})
    assert plain.equity_curve == off.equity_curve
    assert [t.model_dump() for t in plain.trades] == [t.model_dump() for t in off.trades]
