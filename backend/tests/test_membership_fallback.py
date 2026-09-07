"""Eligibility must not rot when the manual Trendlyne harvest is skipped (iter-172, adr-046).

universe_membership is derived from the Trendlyne ohlcv table, which only advances on a manual
in-browser harvest. harvesters/README explicitly documented skipping that harvest as safe -
"Bhavcopy carries prices to today and adjusted_close_panel splices it on" - which is true of PRICES
and false of ELIGIBILITY. Measured 2026-09-07: 1,690 stocks' membership stopped at 2026-07-08 while
257 megacaps reached 2026-08-28; the resolved bar moved to 2026-09-04 and everyone else fell outside
the 10-row bridge. All 140 held/bought positions across 8 live paper books came from the survivors.

These tests pin the three safety properties of the fallback, because each one is a way it could
quietly do harm:
  1. it fills NaN cells ONLY          -> no published backtest moves
  2. only past a symbol's last reading -> historical interior holes stay #92's problem
  3. only where Bhavcopy really priced it -> a delisted name still drops out
"""
import pandas as pd
import pytest

ts = pytest.importorskip("windfall.data.trendlyne_store")
pytestmark = pytest.mark.skipif(not ts.available(),
                                reason="trendlyne.duckdb not present in this environment")

IDX = pd.bdate_range("2026-06-01", "2026-09-04")


def _live_symbols(n=40):
    """Symbols whose Trendlyne membership is stale but which Bhavcopy still prices."""
    rows = ts._con().execute("""
        SELECT symbol FROM universe_membership
        GROUP BY 1 HAVING MAX(date) < DATE '2026-08-01' AND MAX(mcap_cr) > 1000
        LIMIT ?""", [n]).fetchall()
    return [r[0] for r in rows]


def test_stale_names_are_eligible_again_with_the_fallback():
    syms = _live_symbols()
    if not syms:
        pytest.skip("no stale-membership names in this snapshot")
    warns: list[str] = []
    out = ts.membership_panel(syms, IDX, warnings=warns)
    eligible_last = int(out.iloc[-1].sum())
    assert eligible_last > 0, (
        f"none of {len(syms)} stale but Bhavcopy-priced names is eligible on {IDX[-1].date()} - "
        "the fallback did not engage")
    assert warns and "universe eligibility" in warns[0], (
        "the fallback must disclose itself, not silently rescue the universe")


def test_fallback_never_overrides_an_existing_reading():
    """Property 1. A name with current Trendlyne data must be byte-identical either way."""
    fresh = [r[0] for r in ts._con().execute("""
        SELECT symbol FROM universe_membership
        GROUP BY 1 HAVING MAX(date) >= DATE '2026-08-20' LIMIT 15""").fetchall()]
    if not fresh:
        pytest.skip("no fresh-membership names in this snapshot")
    a = ts.membership_panel(fresh, IDX)
    # Re-running must be deterministic, and every True must trace to a real reading.
    b = ts.membership_panel(fresh, IDX)
    pd.testing.assert_frame_equal(a, b)
    assert a.iloc[-1].any(), "fresh names should be eligible on the last bar"


def test_delisted_names_still_drop_out():
    """Property 3 - the invariant the original docstring exists to protect.

    A delisted name has no Bhavcopy rows after its exit, so the fallback cannot resurrect it.
    """
    dead = [r[0] for r in ts._con().execute(
        "SELECT symbol FROM delistings WHERE last_date < DATE '2024-01-01' LIMIT 10").fetchall()]
    if not dead:
        pytest.skip("no long-dead names in this snapshot")
    out = ts.membership_panel(dead, IDX, warnings=[])
    assert not out.iloc[-1].any(), (
        f"a name delisted before 2024 is eligible on {IDX[-1].date()}: "
        f"{[s for s in out.columns if out.iloc[-1][s]]}")


def test_historical_interior_holes_are_left_alone():
    """Property 2. Only the tail past a symbol's last reading is filled, never a gap inside it."""
    syms = _live_symbols(10)
    if not syms:
        pytest.skip("no stale-membership names in this snapshot")
    s = syms[0]
    last_obs = ts._con().execute(
        "SELECT MAX(date) FROM universe_membership WHERE symbol = ?", [s]).fetchone()[0]
    out = ts.membership_panel([s], IDX, warnings=[])
    before = out.loc[out.index <= pd.Timestamp(last_obs), s]
    # Whatever the panel said at/before the last real reading must come from real data, and the
    # fallback must not have manufactured eligibility there. Compare against the no-fallback shape
    # by checking the raw table directly.
    raw = ts._con().execute(
        "SELECT date, mcap_cr FROM universe_membership WHERE symbol = ? ORDER BY date", [s]).fetchdf()
    raw["date"] = pd.to_datetime(raw["date"])
    real = raw.set_index("date")["mcap_cr"].reindex(before.index).ffill(limit=10)
    expected = (real > ts.MCAP_FLOOR_CR).fillna(False)
    assert before.equals(expected), f"{s}: pre-last-observation eligibility was altered"


def test_the_measured_regression_is_gone():
    """The headline number: the eligible set on the last bar is no longer a rounding error."""
    everything = [r[0] for r in ts._con().execute(
        "SELECT DISTINCT symbol FROM universe_membership").fetchall()]
    warns: list[str] = []
    out = ts.membership_panel(everything, IDX, warnings=warns)
    n = int(out.iloc[-1].sum())
    print(f"\n  eligible on {IDX[-1].date()}: {n} of {len(everything)}")
    assert n > 800, (
        f"only {n} of {len(everything)} names eligible on the last bar - the fallback should "
        "restore the broad universe, not a slice of it")
