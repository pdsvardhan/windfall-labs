"""A stock's price series must not depend on who else was requested (iter-172, #820 / adr-044).

adjusted_close_panel used ONE batch-wide `last_tl = MAX(date) over every requested pk` and spliced
Bhavcopy only for `date > last_tl`. A name whose own history ended earlier got leading NaNs for the
gap, which .ffill() cannot repair. Measured 2026-09-04: SCPL requested alone was a clean series from
2026-06-29; requested inside the 98-name paper batch its first value was 2026-07-09, so book_equity
valued it at entry price for its whole holding period — +14.9% reported as a flat 0.0%.

The invariant these tests pin is simple and strong: batch composition must not change a column.
"""
import pandas as pd
import pytest

ts = pytest.importorskip("windfall.data.trendlyne_store")
pytestmark = pytest.mark.skipif(not ts.available(),
                                reason="trendlyne.duckdb not present in this environment")

START = "2026-05-01"


def _stale_and_fresh():
    """One name whose Trendlyne history lags the batch max, and one that reaches it."""
    rows = ts._con().execute("""
        SELECT s.nsecode, MAX(o.date) mx FROM ohlcv o JOIN stocks s ON s.pk = o.pk
        WHERE s.nsecode <> '' GROUP BY 1
        HAVING MAX(o.date) < DATE '2026-08-01' ORDER BY 1 LIMIT 1""").fetchall()
    fresh = ts._con().execute("""
        SELECT s.nsecode FROM ohlcv o JOIN stocks s ON s.pk = o.pk
        WHERE s.nsecode <> '' GROUP BY 1
        HAVING MAX(o.date) >= DATE '2026-08-20' ORDER BY 1 LIMIT 1""").fetchall()
    if not rows or not fresh:
        pytest.skip("need one lagging and one current name in this snapshot")
    return rows[0][0], fresh[0][0]


def test_a_column_is_identical_alone_and_in_a_batch():
    """The core invariant. Before the fix the batched column had leading NaNs."""
    stale, fresh = _stale_and_fresh()
    solo = ts.adjusted_close_panel([stale], start=START, end=None, extend_live=True)
    batch = ts.adjusted_close_panel([stale, fresh], start=START, end=None, extend_live=True)
    pd.testing.assert_series_equal(solo[stale], batch[stale], check_names=False)


def test_a_lagging_name_has_no_interior_holes_in_a_mixed_batch():
    stale, fresh = _stale_and_fresh()
    p = ts.adjusted_close_panel([stale, fresh], start=START, end=None, extend_live=True)
    col = p[stale].dropna()
    interior = p[stale].loc[col.index.min():col.index.max()].isna().sum()
    assert interior == 0, f"{stale} has {interior} interior NaNs inside a mixed batch"


def test_both_names_reach_the_latest_bhavcopy_bar():
    """The splice should carry every live name to the newest close we hold, not just the fresh one."""
    stale, fresh = _stale_and_fresh()
    p = ts.adjusted_close_panel([stale, fresh], start=START, end=None, extend_live=True)
    last = p.index.max()
    for s in (stale, fresh):
        assert pd.notna(p[s].loc[last]), f"{s} has no price on the final bar {last.date()}"


def test_backtests_are_untouched_because_extend_live_is_off():
    """A dated backtest never enters the splice path, so this fix cannot move published results."""
    stale, fresh = _stale_and_fresh()
    a = ts.adjusted_close_panel([stale], start=START, end="2026-06-30", extend_live=False)
    b = ts.adjusted_close_panel([stale, fresh], start=START, end="2026-06-30", extend_live=False)
    pd.testing.assert_series_equal(a[stale], b[stale], check_names=False)
