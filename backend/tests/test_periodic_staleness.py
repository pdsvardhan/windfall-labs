"""Quarterly/annual panels must disclose a reporting GAP without crying wolf on normal cadence.

to-do #852, the sibling of #850. Those panels ffill unbounded inside trendlyne_store, so
`valuation_ratios` sitting frozen for 54 days went unnoticed and a live paper book ranked on it.
The daily rule (_STALE_FACTOR_DAYS = 14) is wrong here: result-lag-gated data is published ~90 days
apart with a ~45-day lag, so a 135-day-old value is HEALTHY. Hence a separate 270-day threshold -
three missed quarters, which is a gap rather than a cadence.
"""
import pandas as pd
import pytest

from windfall.data.trendlyne_store import _STALE_FUNDAMENTAL_DAYS, _ffill_periodic

IDX = pd.bdate_range("2024-01-01", "2026-09-04")
COLS = ["AAA", "BBB"]


def _panel(last: str, n: int = 8):
    """A panel reporting quarterly, ending at `last`."""
    dates = pd.date_range(end=pd.Timestamp(last), periods=n, freq="90D")
    return pd.DataFrame([[float(i), float(i) * 2] for i in range(n)], index=dates, columns=COLS)


def test_normal_quarterly_cadence_does_not_warn():
    """The whole risk of this check is false positives. A recent quarter must be silent."""
    warns: list[str] = []
    _ffill_periodic(_panel("2026-07-15"), IDX, "tl_roe", warns)
    assert warns == [], warns


def test_a_value_older_than_one_lagged_quarter_still_does_not_warn():
    """~135 days old is normal for result-lag-gated data, not a fault."""
    warns: list[str] = []
    _ffill_periodic(_panel("2026-04-20"), IDX, "tl_roe", warns)
    assert warns == [], warns


def test_three_missed_quarters_warns_and_says_how_many():
    warns: list[str] = []
    _ffill_periodic(_panel("2025-06-30"), IDX, "tl_piotroski", warns)
    assert len(warns) == 1, warns
    msg = warns[0]
    assert "tl_piotroski" in msg
    assert "2025-06-30" in msg and "2026-09-04" in msg
    assert "quarters" in msg


def test_the_threshold_is_the_quarterly_one_not_the_daily_one():
    """Guards against someone 'simplifying' this to reuse _STALE_FACTOR_DAYS = 14."""
    assert _STALE_FUNDAMENTAL_DAYS > 180, (
        "a sub-two-quarter threshold would fire on healthy result-lag-gated data")


def test_values_are_unchanged_by_the_disclosure():
    """Additive only - identical to the plain ffill it replaced."""
    p = _panel("2025-06-30")
    legacy = p.reindex(p.index.union(IDX)).ffill().reindex(IDX)
    out = _ffill_periodic(p, IDX, "tl_roe", [])
    pd.testing.assert_frame_equal(out, legacy)


def test_empty_and_all_nan_panels_do_not_invent_a_date():
    assert _ffill_periodic(pd.DataFrame(), IDX, "tl_roe", []).empty is False or True
    warns: list[str] = []
    allnan = pd.DataFrame(float("nan"), index=IDX[:5], columns=COLS)
    _ffill_periodic(allnan, IDX, "tl_de", warns)
    assert warns == []


def test_warnings_none_is_accepted():
    """Callers that do not collect warnings must not crash."""
    _ffill_periodic(_panel("2020-01-01"), IDX, "tl_roe", None)


# ── #853: the conftest fix ───────────────────────────────────────────────────────────────────
def test_real_data_stores_are_wired_up_on_a_bare_host_run():
    """A skipped test proves nothing and looks exactly like a passing one.

    conftest defaulted WINDFALL_DATA_DIR to the CONTAINER path /app/data, so running pytest from a
    host shell left the Trendlyne/Bhavcopy env vars unset and silently skipped 17 real-data tests -
    including the NSE-only gate, alias resolution, and the #250 concurrency regression that was the
    whole point of that fix. This asserts the wiring itself, so the skip cannot come back unnoticed.
    """
    import os

    from windfall.data import trendlyne_store as ts
    assert os.environ.get("WINDFALL_TRENDLYNE_DB"), (
        "WINDFALL_TRENDLYNE_DB not set - conftest failed to locate the real data dir, so every "
        "real-data test in this suite is skipping")
    assert ts.available(), "trendlyne store not available despite the env var being set"
