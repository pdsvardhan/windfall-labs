"""iter-34 (adr-025): ISIN-based ticker-rename/alias resolution for Bhavcopy-keyed lookups.

A company that changes ticker (NAVA was NBVENTURES until 2022) keeps its pre-rename history in
Bhavcopy under the OLD ticker. Symbol-keyed lookups (turnover/ADTV, dead-name prices, pit-mcap) must
resolve renames via ISIN, else renamed names spuriously fail the liquidity filter and lose price/
membership history in their pre-rename window. Skips when trendlyne.duckdb is absent."""
import pytest

from windfall.data import trendlyne_store as ts

pytestmark = pytest.mark.skipif(not ts.available(), reason="trendlyne.duckdb not present")


def test_alias_links_renamed_tickers():
    al = ts._ticker_aliases()
    assert "NBVENTURES" in al.get("NAVA", frozenset())
    assert "NAVA" in al.get("NBVENTURES", frozenset())


def test_traded_value_recovers_prerename_turnover():
    """ADTV for NAVA in 2021 must be non-empty (recovered from its NBVENTURES rows) — pre-fix it was
    empty, so NAVA wrongly failed adtv_cr>10 despite being a real, liquid NSE name."""
    tv = ts.traded_value_panel(["NAVA"], "2021-06-01", "2021-08-15")
    assert not tv.empty and "NAVA" in tv.columns
    assert tv["NAVA"].notna().sum() > 20


def test_no_alias_overmerge():
    """Alias sets must stay small (renames are 2-3 tickers); a huge set would mean ISIN reuse merged
    unrelated companies."""
    al = ts._ticker_aliases()
    big = {k: sorted(v) for k, v in al.items() if len(v) > 6}
    assert not big, f"suspiciously large alias sets (possible ISIN reuse): {list(big)[:10]}"
