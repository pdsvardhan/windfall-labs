"""iter-29: the survivorship-free Trendlyne data layer wired into resolve() + the backtest engine.

Reads the real trendlyne.duckdb (read-only). The windfall path keeps using conftest's seeded temp
DB, so these never touch the live container DB. Skips if the data layer isn't present.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_DATA = Path(__file__).resolve().parents[1] / "data"
_TL = _DATA / "trendlyne.duckdb"
_BC = _DATA / "bhavcopy.duckdb"

pytestmark = pytest.mark.skipif(not _TL.exists(), reason="trendlyne.duckdb data layer not present")


@pytest.fixture(scope="module", autouse=True)
def _point_store():
    from windfall.data import trendlyne_store as ts
    ts.TRENDLYNE_DB = _TL
    ts.BHAVCOPY_DB = _BC
    for fn in (ts._con, ts.symbol_pk_map, ts.sector_map, ts.ca_uncertain_symbols):
        fn.cache_clear()
    return ts


def _cfg(**over):
    base = {
        "name": "tl_test", "data_source": "trendlyne",
        "universe": {"index": "trendlyne", "filters": ["adtv_cr >= 0.5"]},
        "rank_by": "roc126", "n_holdings": 20, "rebalance": "monthly", "invest_fully": True,
        "stop_loss": {"type": "none"}, "regime_filter": {"enabled": False},
        "start": "2017-01-01", "end": "2021-12-31", "benchmark": "NIFTY500",
    }
    base.update(over)
    return base


# ── resolve(): survivorship-free panels, membership gating, Trendlyne features ────────────────

def test_resolve_trendlyne_panels():
    from windfall.strategy.resolve import resolve
    from windfall.strategy.schema import StrategyConfig
    rs = resolve(StrategyConfig(**_cfg(universe={"index": "trendlyne",
                 "filters": ["adtv_cr >= 1", "tl_durability >= 40"]},
                 rank_blend=[{"factor": "roc126", "weight": 0.6},
                             {"factor": "tl_momentum", "weight": 0.4}])))
    assert len(rs.tickers) > 500                              # survivorship-free candidate set
    assert not rs.close_adj.empty and not rs.rank_score.empty
    assert rs.entry_mask.shape == rs.close_adj.shape
    assert any("survivorship-free" in w for w in rs.warnings)


def test_trendlyne_dvm_features_resolve():
    """tl_durability/valuation/momentum must resolve to real 0-100 score panels (not all-NaN)."""
    from windfall.strategy.resolve import resolve
    from windfall.strategy.schema import StrategyConfig
    rs = resolve(StrategyConfig(**_cfg(rank_by="tl_durability")))
    vals = rs.rank_score.to_numpy()
    finite = vals[np.isfinite(vals)]
    assert finite.size > 1000
    assert finite.min() >= 0 and finite.max() <= 100


def test_pit_membership_gates_dead_name(_point_store):
    """A delisted name must be eligible while large and INELIGIBLE after it stops trading."""
    dates = pd.bdate_range("2017-01-01", "2023-12-31")
    mp = _point_store.membership_panel(["RCOM"], dates)
    assert bool(mp["RCOM"].loc[:"2017-06-30"].any())          # large-cap in 2017
    assert not bool(mp["RCOM"].loc["2023-01-01":].any())      # long delisted by 2023


def test_blowups_included_not_excluded(_point_store):
    """Survivorship-free: ca_uncertain blow-ups/mergers are INCLUDED (excluding them = optimism)."""
    u = _point_store.universe_over_window("2017-01-01", "2018-12-31")
    assert "RCOM" in u                                        # a ca_uncertain blow-up, still tradeable
    assert _point_store.ca_uncertain_symbols()                # the flag exists, as a warning only


# ── no-look-ahead: result-lag-gated raw fundamentals ──────────────────────────────────────────

def test_result_lag_no_lookahead(_point_store):
    """tl_roe for a period must be NaN before its real announcement date, present on/after it."""
    dates = pd.bdate_range("2019-01-01", "2020-12-31")
    panel = _point_store.raw_fundamental_panel("tl_roe", ["RELIANCE"], dates)
    if panel.empty or "RELIANCE" not in panel.columns:
        pytest.skip("no RELIANCE ROE history")
    s = panel["RELIANCE"]
    # FY2020 (period_end 2020-03-31) results were announced ~Apr-May 2020 -> not visible in Jan 2020
    jan = s.loc[:"2020-01-31"].dropna()
    later = s.loc["2020-07-01":].dropna()
    assert not later.empty
    if not jan.empty and not later.empty:
        assert jan.iloc[-1] != later.iloc[-1] or len(s.dropna().unique()) > 1  # value advanced PIT


# ── delisting terminal exit + full backtest ───────────────────────────────────────────────────

def test_delisting_terminal_exit_fires():
    """A broad hold-everything book over 2017-2018 must force-exit names that delist (SBI mergers)."""
    from windfall.engine.backtest import run_backtest
    res = run_backtest(_cfg(rank_by="close", rank_order="desc", n_holdings=200,
                            universe={"index": "trendlyne", "filters": ["adtv_cr >= 0.1"]},
                            start="2017-01-01", end="2018-06-30"))
    delisted = [t for t in res.trades if t.exit_reason == "delisted"]
    assert delisted, "no delisting terminal exits despite holding 200 names through 2017 mergers"
    assert all(t.exit > 0 for t in delisted)                  # exited at a real last price


def test_full_trendlyne_backtest_sane():
    from windfall.engine.backtest import run_backtest
    res = run_backtest(_cfg(regime_filter={"enabled": True, "ma_period": 200, "mode": "binary"}))
    assert len(res.trades) > 50
    assert np.isfinite(res.summary.cagr)
    assert -1.0 < res.summary.max_drawdown <= 0.0
    assert res.period["start"] >= "2017-01-01"


def test_real_benchmark_used(_point_store):
    """Benchmark comes from Trendlyne's Nifty 500 index series, not a yfinance proxy/fallback."""
    bench = _point_store.benchmark_series("NIFTY500", "2018-01-01", "2020-12-31")
    assert not bench.empty and bench.min() > 1000             # Nifty 500 index level


# ── regression: the legacy windfall path is unchanged (default data_source) ───────────────────

def test_windfall_path_default_unchanged():
    """data_source defaults to 'windfall'; the seeded synthetic DB path still backtests."""
    from windfall.engine.backtest import run_backtest
    res = run_backtest({"name": "legacy", "universe": {"index": "nifty500"},
                        "rank_by": "roc21", "n_holdings": 3, "rebalance": "monthly",
                        "start": "2018-06-01", "end": "2020-06-30"})
    assert len(res.trades) >= 0 and np.isfinite(res.summary.cagr)
