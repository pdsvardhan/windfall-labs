"""Multi-strategy rotation overlay (fund-of-funds across self-timed sleeves + cash)."""
import pandas as pd

from windfall.engine.rotation import run_rotation

BASE = {
    "name": "sleeve", "universe": {"index": "nifty500", "filters": []},
    "entry_filters": ["close > sma50"], "rank_order": "desc",
    "n_holdings": 3, "weighting": "equal", "invest_fully": True,
    "rebalance": "monthly", "entry_fill": "next_open",
    "stop_loss": {"type": "none"}, "take_profit": {"type": "none"},
    "start": "2018-06-01", "end": "2020-12-31", "benchmark": "NIFTY500",
}
SLEEVE_A = {**BASE, "name": "sleeveA", "rank_by": "roc21"}
SLEEVE_B = {**BASE, "name": "sleeveB", "rank_by": "roc63"}


def test_rotation_runs_and_is_finite():
    out = run_rotation([SLEEVE_A, SLEEVE_B], rebalance="monthly", lookback_days=42)
    assert out["equity_curve"] and len(out["equity_curve"]) > 100
    s = out["summary"]
    assert pd.notna(s["cagr"]) and pd.notna(s["max_drawdown"])
    assert 0.0 <= s["exposure"] <= 1.0 + 1e-9
    assert len(out["sleeves"]) == 2
    assert any("UPPER BOUND" in w for w in out["warnings"])  # switch-cost approximation disclosed


def test_rotation_deterministic():
    a = run_rotation([SLEEVE_A, SLEEVE_B], lookback_days=42)
    b = run_rotation([SLEEVE_A, SLEEVE_B], lookback_days=42)
    assert a["equity_curve"] == b["equity_curve"]
    assert a["allocations"] == b["allocations"]


def test_rotation_holds_cash_when_floor_unreachable():
    """An impossibly high momentum floor means no sleeve ever 'works' -> the book stays in cash:
    ~zero exposure and a flat curve (no spurious return from thin air)."""
    out = run_rotation([SLEEVE_A, SLEEVE_B], lookback_days=42, momentum_floor=100.0)
    assert out["summary"]["exposure"] < 1e-6
    assert abs(out["summary"]["total_return"]) < 1e-6
    assert out["allocations"] == [] or all(a["cash"] == 1.0 for a in out["allocations"])


def test_rotation_top_k_limits_concentration():
    """top_k=1 must never allocate to more than one sleeve at a time."""
    out = run_rotation([SLEEVE_A, SLEEVE_B], lookback_days=42, top_k=1)
    for a in out["allocations"]:
        assert len(a["weights"]) <= 1


def test_rotation_requires_two_sleeves():
    try:
        run_rotation([SLEEVE_A])
        assert False, "expected ValueError for a single sleeve"
    except ValueError:
        pass
