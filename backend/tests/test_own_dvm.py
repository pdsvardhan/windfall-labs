"""Tests for our own reproducible D/V/M scores (iter-23)."""
import numpy as np
import pandas as pd

from windfall.scores import own_dvm as own
from windfall.scores.own_dvm import _blend_pct
from windfall.strategy.readiness import data_readiness
from windfall.strategy.resolve import resolve
from windfall.strategy.schema import StrategyConfig, Universe


def _panel(rows):
    idx = pd.bdate_range("2020-01-01", periods=len(rows))
    return pd.DataFrame(rows, index=idx, columns=["A", "B", "C", "D"])


def test_blend_pct_scales_to_0_100_and_orders():
    s = _blend_pct([(_panel([[1.0, 2.0, 3.0, 4.0]]), 1.0)])
    assert s.iloc[0].min() >= 0.0 and s.iloc[0].max() <= 100.0
    assert s.iloc[0]["D"] > s.iloc[0]["A"]          # higher input -> higher percentile score


def test_blend_pct_renormalizes_over_present_inputs():
    p1 = _panel([[1.0, 2.0, 3.0, 4.0]])
    p_missing = _panel([[np.nan, np.nan, np.nan, np.nan]])
    blended = _blend_pct([(p1, 0.5), (p_missing, 0.5)])
    only = _blend_pct([(p1, 0.5)])
    assert np.allclose(blended.iloc[0].values, only.iloc[0].values)  # missing input drops out


def test_valuation_excludes_loss_makers_and_prefers_cheap():
    s = own.valuation_own(_panel([[10.0, 20.0, -5.0, 40.0]]),   # C is loss-making (P/E<0)
                          _panel([[1.0, 2.0, 3.0, 4.0]]),
                          _panel([[1.0, 1.0, 1.0, 1.0]]))
    assert not np.isnan(s.iloc[0]["C"])             # still scored (PE component just dropped)
    assert s.iloc[0]["A"] > s.iloc[0]["D"]          # cheaper P/E -> higher valuation score


def test_durability_handles_all_missing_gracefully():
    nan = _panel([[np.nan] * 4])
    s = own.durability_own(nan, nan, nan, nan, nan, nan)
    assert s is not None and s.iloc[0].isna().all()  # no inputs -> all-NaN, no crash


def test_momentum_own_resolves_as_a_feature_in_0_100():
    cfg = StrategyConfig(name="m", universe=Universe(index="nifty500", filters=["momentum_own > 0"]),
                         rank_by="momentum_own", start="2018-01-01")
    finite = resolve(cfg).rank_score.to_numpy()
    finite = finite[~np.isnan(finite)]
    assert finite.size > 0 and finite.min() >= 0.0 and finite.max() <= 100.0


def test_readiness_momentum_own_is_fully_backtestable():
    cfg = StrategyConfig(universe=Universe(filters=["momentum_own > 50"]), rank_by="momentum_own")
    assert data_readiness(cfg)["verdict"] == "fully-backtestable"   # price-only score


def test_readiness_durability_own_is_fundamental_gated():
    cfg = StrategyConfig(universe=Universe(filters=["durability_own > 50"]))
    r = data_readiness(cfg)
    assert r["verdict"] in ("live-only", "blocked")
    assert "durability_own" in r["fundamentals_in_filter"]
