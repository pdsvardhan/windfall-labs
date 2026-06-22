"""iter-33 (adr-024): hard NSE-only universe gate.

Trendlyne scores + prices BSE-only names on BSE; without a gate they were eligible (priced on BSE
closes) and only excluded by user-set liquidity filters. This makes NSE-only a guarantee: a name is
eligible iff it has NSE-traded presence (Bhavcopy EQ). Skips when trendlyne.duckdb is absent."""
import pandas as pd
import pytest

from windfall.data import trendlyne_store as ts

pytestmark = pytest.mark.skipif(not ts.available(), reason="trendlyne.duckdb not present")


def test_universe_functions_contain_no_non_nse_names():
    nse = ts._nse_symbols()
    uow = ts.universe_over_window("2018-01-01", "2024-12-31")
    pu = ts.pit_universe(ts._con().execute("SELECT MAX(date) FROM universe_membership").fetchone()[0])
    assert uow and pu
    assert [s for s in uow if s not in nse] == []
    assert [s for s in pu if s not in nse] == []


def test_known_nse_names_retained():
    uow = set(ts.universe_over_window("2018-01-01", "2024-12-31"))
    assert {"RELIANCE", "TCS"} <= uow


def test_bse_only_name_never_eligible():
    """A BSE-only name (Trendlyne-priced, zero NSE turnover) must be excluded from the universe and
    return all-False membership even if explicitly requested."""
    nse = ts._nse_symbols()
    # find a real BSE-only name currently in the data (eligible-but-not-NSE before the gate)
    uni = [r[0] for r in ts._con().execute("SELECT DISTINCT symbol FROM universe_membership").fetchall()]
    bse_only = next((s for s in uni if s not in nse), None)
    assert bse_only is not None, "expected at least one BSE-only name in the raw membership table"
    assert bse_only not in ts.universe_over_window("2010-01-01", "2026-12-31")
    mp = ts.membership_panel([bse_only], pd.bdate_range("2022-01-01", "2024-12-31"))
    assert not bool(mp.values.any())
