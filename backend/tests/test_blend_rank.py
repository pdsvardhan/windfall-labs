"""Tests for the engine-fidelity bundle (iter-22): blend ranker, quarterly, max-weight, readiness."""
import numpy as np
import pandas as pd

from windfall.engine.backtest import _apply_max_weight, _rebalance_dates, run_backtest
from windfall.strategy.readiness import data_readiness
from windfall.strategy.resolve import resolve
from windfall.strategy.schema import RankFactor, StrategyConfig, Universe


# ── quarterly rebalance ──────────────────────────────────────────────────────
def test_quarterly_rebalance_dates():
    idx = pd.bdate_range("2018-01-01", periods=700)  # ~2.8 years
    q = _rebalance_dates(idx, "quarterly")
    assert 9 <= len(q) <= 13                          # ~4 per year
    assert len(q) < len(_rebalance_dates(idx, "monthly"))  # quarterly is coarser than monthly


# ── max-weight-per-stock cap ─────────────────────────────────────────────────
def test_max_weight_caps_and_redistributes():
    w = _apply_max_weight({0: 0.5, 1: 0.3, 2: 0.2}, 0.4)
    assert max(w.values()) <= 0.4 + 1e-9             # nobody exceeds the cap
    assert abs(sum(w.values()) - 1.0) < 1e-9         # fully invested preserved


def test_max_weight_all_at_cap_leaves_residual():
    # cap * n < 1 -> everyone sits at the cap and the rest stays in cash
    w = _apply_max_weight({0: 0.34, 1: 0.33, 2: 0.33}, 0.3)
    assert all(x <= 0.3 + 1e-9 for x in w.values())
    assert sum(w.values()) <= 0.9 + 1e-9


# ── percentile-blend ranker ──────────────────────────────────────────────────
def _blend_cfg(factors, filters=None):
    return StrategyConfig(name="t", universe=Universe(index="nifty500", filters=filters or []),
                          entry_filters=[], rank_blend=factors, start="2018-01-01")


def test_blend_score_is_a_percentile_in_unit_interval():
    rs = resolve(_blend_cfg([RankFactor(factor="roc125", weight=0.6),
                             RankFactor(factor="roc21", weight=0.4)]))
    finite = rs.rank_score.to_numpy()[~np.isnan(rs.rank_score.to_numpy())]
    assert finite.size > 0
    assert finite.min() >= 0.0 and finite.max() <= 1.0   # weighted-mean percentile in [0,1]
    assert finite.min() < finite.max()                   # non-degenerate (actually discriminates)


def test_single_factor_blend_preserves_raw_factor_ordering():
    # A one-factor percentile blend must rank names in exactly the raw factor's order
    # (deterministic, unlike comparing synthetic drifts over a single momentum window).
    blend = resolve(_blend_cfg([RankFactor(factor="roc125", weight=1.0)])).rank_score
    raw = resolve(StrategyConfig(name="r", universe=Universe(index="nifty500"),
                                 rank_by="roc125", start="2018-01-01")).rank_score
    last = blend.dropna(how="all").index[-1]
    b = blend.loc[last].dropna()
    r = raw.loc[last].reindex(b.index).dropna()
    b = b.reindex(r.index)
    assert list(b.sort_values().index) == list(r.sort_values().index)  # identical ordering


def test_blend_is_blank_tolerant_to_missing_fundamentals():
    # No fundamentals snapshot in the test DB -> piotroski is all-NaN and must be DROPPED,
    # with roc125 carrying the blend (not the whole score going NaN).
    rs = resolve(_blend_cfg([RankFactor(factor="roc125", weight=0.5),
                             RankFactor(factor="piotroski", weight=0.5)]))
    assert rs.rank_score.notna().to_numpy().any()        # still has a usable score
    assert any("piotroski" in w and "no data" in w for w in rs.warnings)


# ── data-readiness verdicts ──────────────────────────────────────────────────
def test_readiness_fully_backtestable_price_only():
    cfg = StrategyConfig(universe=Universe(filters=["close > sma50"]),
                         rank_blend=[RankFactor(factor="roc125")])
    r = data_readiness(cfg)
    assert r["verdict"] == "fully-backtestable"
    assert r["backtestable_from"] is not None


def test_readiness_price_backtestable_with_fundamental_rank_factor():
    cfg = StrategyConfig(universe=Universe(filters=["close > sma50"]),
                         rank_blend=[RankFactor(factor="roc125"), RankFactor(factor="piotroski")])
    r = data_readiness(cfg)
    assert r["verdict"] == "price-backtestable"          # blend is blank-tolerant
    assert "piotroski" in r["fundamentals_in_rank"]


def test_readiness_blocked_when_fundamental_in_filter():
    # A fundamental in a hard FILTER cannot be NaN-tolerated -> not backtestable on history.
    cfg = StrategyConfig(universe=Universe(filters=["durability > 50"]))
    r = data_readiness(cfg)
    assert r["verdict"] in ("live-only", "blocked")      # 'blocked' here: no snapshot in test DB
    assert "durability" in r["fundamentals_in_filter"]


# ── end-to-end: a quarterly price-blend backtest actually trades over history ─
def test_quarterly_blend_backtest_runs_end_to_end():
    cfg = StrategyConfig(name="qb", universe=Universe(index="nifty500", filters=[]),
                         rank_blend=[RankFactor(factor="roc125"), RankFactor(factor="roc21")],
                         rebalance="quarterly", n_holdings=3, max_weight_per_stock=0.5,
                         start="2018-01-01")
    res = run_backtest(cfg)
    assert res.summary.n_trades > 0                      # the blend produced real picks over history
    assert res.period["years"] > 1
