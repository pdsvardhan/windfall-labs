"""Peer-relative features computed from panels we hold, not read from the snapshot (iter-172).

sector_pe / industry_pe / rs_nifty_* / rs_sector_* used to come from the Trendlyne Data Downloader
snapshot: NaN before the export date (so useless in a backtest - resolve.py already warned about
exactly that for pe_to_sector) and covering 79% of the universe, because the export caps at 2,000
rows and truncates alphabetically at M. Computing them buys full history and every name.

No saved strategy referenced any of these (0 of 289 checked), so nothing re-baselines.
"""
import numpy as np
import pandas as pd
import pytest

from windfall.strategy.resolve import _peer_stat, _relative_return

IDX = pd.bdate_range("2024-01-01", periods=120)
COLS = ["AAA", "BBB", "CCC", "DDD"]
GROUPS = {"AAA": "Tech", "BBB": "Tech", "CCC": "Bank", "DDD": "Bank"}


def _panel(values):
    """Constant-per-column panel."""
    return pd.DataFrame({c: [v] * len(IDX) for c, v in zip(COLS, values)}, index=IDX)


# ── peer median ──────────────────────────────────────────────────────────────────────────────
def test_peer_median_is_per_group_not_across_everything():
    out = _peer_stat(_panel([10, 20, 100, 200]), GROUPS, IDX, COLS, positive_only=True)
    assert out.iloc[-1]["AAA"] == 15    # median(10, 20)
    assert out.iloc[-1]["BBB"] == 15
    assert out.iloc[-1]["CCC"] == 150   # median(100, 200)
    assert out.iloc[-1]["DDD"] == 150


def test_median_not_mean_so_one_absurd_multiple_cannot_move_the_peer_group():
    """The whole reason for median: a near-zero-earnings company prints a P/E in the thousands."""
    normal = _peer_stat(_panel([10, 20, 100, 200]), GROUPS, IDX, COLS, positive_only=True)
    skewed = _peer_stat(_panel([10, 5000, 100, 200]), GROUPS, IDX, COLS, positive_only=True)
    assert normal.iloc[-1]["AAA"] == 15
    assert skewed.iloc[-1]["AAA"] == 2505 or skewed.iloc[-1]["AAA"] == pytest.approx(2505)
    # With only two members the median IS the mean, so prove the point on a 3-member group.
    g = {"AAA": "T", "BBB": "T", "CCC": "T", "DDD": "X"}
    s3 = _peer_stat(_panel([10, 20, 5000, 1]), g, IDX, COLS, positive_only=True)
    assert s3.iloc[-1]["AAA"] == 20, "median of (10,20,5000) is 20; the mean would be ~1677"


def test_non_positive_multiples_are_excluded_not_averaged_in():
    """A loss-maker's negative P/E is not a cheap valuation."""
    out = _peer_stat(_panel([-50, 10, 20, 30]), {c: "One" for c in COLS}, IDX, COLS,
                     positive_only=True)
    assert out.iloc[-1]["AAA"] == 20, "median of the POSITIVE members (10,20,30)"


def test_returns_may_be_negative_so_positive_only_is_off_for_them():
    out = _peer_stat(_panel([-0.10, -0.20, 0.10, 0.20]), GROUPS, IDX, COLS, positive_only=False)
    assert out.iloc[-1]["AAA"] == pytest.approx(-0.15)


def test_an_ungrouped_name_falls_into_its_own_unknown_bucket():
    out = _peer_stat(_panel([10, 20, 100, 200]), {"AAA": "Tech"}, IDX, COLS, positive_only=True)
    assert out.iloc[-1]["AAA"] == 10          # alone in Tech
    assert out.iloc[-1]["BBB"] == out.iloc[-1]["CCC"]   # all the rest share 'Unknown'


# ── relative return ──────────────────────────────────────────────────────────────────────────
def _ramp(pct_by_col):
    """A panel where each column compounds steadily to the given total over the window."""
    return pd.DataFrame(
        {c: np.linspace(100.0, 100.0 * (1 + p), len(IDX)) for c, p in zip(COLS, pct_by_col)},
        index=IDX)


def test_relative_to_a_benchmark_is_a_percentage_point_difference():
    close = _ramp([0.20, 0.10, 0.0, -0.10])
    bench = pd.Series(np.linspace(100.0, 110.0, len(IDX)), index=IDX)   # +10%
    out = _relative_return(close, 21, bench=bench)
    last = out.iloc[-1]
    # AAA outran the index; DDD lagged it. Ordering is the contract, exact size follows the ramp.
    assert last["AAA"] > last["BBB"] > last["CCC"] > last["DDD"]
    assert last["BBB"] == pytest.approx(0.0, abs=0.5), "same slope as the index -> ~0 excess"


def test_relative_to_sector_uses_the_peer_median_not_the_index():
    close = _ramp([0.30, 0.10, 0.30, 0.10])
    out = _relative_return(close, 21, groups=GROUPS)
    last = out.iloc[-1]
    # Within each 2-member sector the median is the midpoint, so the pair is symmetric about 0.
    assert last["AAA"] == pytest.approx(-last["BBB"], abs=1e-6)
    assert last["CCC"] == pytest.approx(-last["DDD"], abs=1e-6)


def test_a_name_matching_its_sector_exactly_scores_zero():
    close = _ramp([0.20, 0.20, 0.05, 0.05])
    out = _relative_return(close, 21, groups=GROUPS)
    assert out.iloc[-1].abs().max() == pytest.approx(0.0, abs=1e-9)


def test_output_is_shaped_like_the_input():
    close = _ramp([0.1, 0.2, 0.3, 0.4])
    out = _relative_return(close, 63, groups=GROUPS)
    assert out.shape == close.shape
    assert list(out.columns) == COLS
    assert out.iloc[:63].isna().all().all(), "no return before the window has filled"
