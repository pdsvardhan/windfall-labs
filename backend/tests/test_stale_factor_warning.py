"""A ffilled daily Trendlyne factor must announce how stale its source is.

Regression test for iter-172 / to-do #850. resolve() forward-fills the daily tl_* panels onto the
price index, which is correct behaviour and was also silently hiding an abandoned table: on
2026-09-07 valuation_ratios had been frozen at 2026-07-15 for 54 days while dvm_history was current
to 2026-09-04, so CMP_valmom_m_20 - a live paper book - ranked half its book on stale multiples,
returned as_of=2026-09-04, and put nothing in warnings[].

The ffill is deliberately NOT removed here: carrying the last published value forward is right. What
these tests pin is that the carry is disclosed once it exceeds the pit_universe lookback window.
"""
import pandas as pd
import pytest

from windfall.strategy.resolve import _STALE_FACTOR_DAYS, _ffill_daily_tl

COLS = ["AAA", "BBB"]


def _price_index(days: int = 400, end: str = "2026-09-04") -> pd.DatetimeIndex:
    return pd.bdate_range(end=pd.Timestamp(end), periods=days)


def _panel(idx: pd.DatetimeIndex, last: str) -> pd.DataFrame:
    """A factor panel published daily up to and including `last`."""
    obs = idx[idx <= pd.Timestamp(last)]
    return pd.DataFrame(
        [[float(i), float(i) * 2] for i in range(len(obs))], index=obs, columns=COLS)


def test_fresh_panel_warns_nothing():
    idx = _price_index()
    warnings: list[str] = []
    out = _ffill_daily_tl(_panel(idx, "2026-09-04"), "tl_durability", idx, COLS, warnings)
    assert warnings == []
    assert out.index.equals(idx)
    assert not out.iloc[-1].isna().any()


def test_panel_stale_within_the_window_still_warns_nothing():
    """A holiday gap or a scrape that missed a few days is normal - do not cry wolf."""
    idx = _price_index()
    last = idx[idx <= idx.max() - pd.Timedelta(days=_STALE_FACTOR_DAYS - 3)].max()
    warnings: list[str] = []
    _ffill_daily_tl(_panel(idx, str(last.date())), "tl_pe", idx, COLS, warnings)
    assert warnings == []


def test_abandoned_panel_warns_and_names_the_factor_and_the_age():
    """The measured 2026-09-07 case: tl_pe last published 2026-07-15, prices to 2026-09-04."""
    idx = _price_index()
    warnings: list[str] = []
    out = _ffill_daily_tl(_panel(idx, "2026-07-15"), "tl_pe", idx, COLS, warnings)

    assert len(warnings) == 1, warnings
    msg = warnings[0]
    assert "tl_pe" in msg
    assert "2026-07-15" in msg and "2026-09-04" in msg
    assert "51 days" in msg, msg          # (2026-09-04 - 2026-07-15).days
    # The ffill still happened - the values are carried, they are just now disclosed.
    assert not out.iloc[-1].isna().any()
    assert out.iloc[-1].equals(out.loc[pd.Timestamp("2026-07-15")])


def test_warning_does_not_alter_the_values_it_reports_on():
    """Additive only: a stale panel resolves to exactly what the plain ffill produced before."""
    idx = _price_index()
    panel = _panel(idx, "2026-07-15")
    legacy = panel.reindex(index=idx, columns=COLS).ffill()   # the pre-fix expression, verbatim
    out = _ffill_daily_tl(panel, "tl_pe", idx, COLS, [])
    pd.testing.assert_frame_equal(out, legacy)


@pytest.mark.parametrize("panel", [None, pd.DataFrame()])
def test_missing_panel_is_shaped_not_crashed(panel):
    idx = _price_index(30)
    warnings: list[str] = []
    out = _ffill_daily_tl(panel, "tl_pbv", idx, COLS, warnings)
    assert out.shape == (len(idx), len(COLS))
    assert out.isna().all().all()
    assert warnings == []       # absent is not stale - _TL_FEATURES already warns for unresolved


def test_all_nan_panel_does_not_claim_a_bogus_observation_date():
    """A panel with rows but no values has no 'last published' date to report."""
    idx = _price_index(30)
    empty = pd.DataFrame(float("nan"), index=idx[:5], columns=COLS)
    warnings: list[str] = []
    _ffill_daily_tl(empty, "tl_peg", idx, COLS, warnings)
    assert warnings == []
