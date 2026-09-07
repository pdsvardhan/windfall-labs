"""A stub out-of-sample fold must not carry a full fold's weight (iter-172, to-do #251).

The trailing fold is clipped to the configured end date, so it can be a few days long — measured as
short as 8 days — while `_avg` weighted it exactly as heavily as a full year. A handful of noisy
days then moved the robust / likely-curve-fit verdict for the entire strategy.

These use a stubbed run_backtest/sweep so the arithmetic is deterministic and the assertion is about
the WEIGHTING, not about any particular strategy's returns.
"""
import datetime as dt

import pytest

from windfall.walkforward import walkforward as wf


@pytest.fixture()
def fake_engine(monkeypatch):
    """IS always +1.0; OOS is +1.0 on full folds and catastrophically negative on the stub."""
    calls: list[dict] = []

    def fake_sweep(cfg, grid, metric="sharpe"):
        return {"ranked": [{"overrides": {}, "value": 1.0}]}

    class _R:
        def __init__(self, v):
            self._v = v

        @property
        def summary(self):
            class S:
                def model_dump(_self):
                    return {"sharpe": self._v}
            return S()

    def fake_run_backtest(cfg):
        start = dt.date.fromisoformat(cfg["start"])
        end = dt.date.fromisoformat(cfg["end"])
        days = (end - start).days
        calls.append({"days": days})
        return _R(-20.0 if days < 90 else 1.0)   # the stub fold is a disaster

    monkeypatch.setattr(wf, "sweep", fake_sweep)
    monkeypatch.setattr(wf, "run_backtest", fake_run_backtest)
    return calls


BASE = {"name": "t", "start": "2015-01-01", "end": "2022-02-10",   # ends mid-fold on purpose
        "universe": {"index": "nifty500", "filters": []}, "rank_by": "roc21"}


def test_a_short_trailing_fold_is_excluded_from_the_averages(fake_engine):
    out = wf.walk_forward(BASE, {"n_holdings": [10]}, metric="sharpe", is_years=3.0, oos_years=1.0)

    stubs = [w for w in out["windows"] if w["truncated"]]
    assert stubs, "this date range should produce a clipped trailing fold"
    assert out["n_windows_scored"] == out["n_windows"] - len(stubs)
    # The -20 stub must not drag the average: full folds are all +1.0.
    assert out["oos_avg"] == pytest.approx(1.0), (
        f"stub fold leaked into the average: oos_avg={out['oos_avg']}")
    assert out["verdict"] == "robust"


def test_the_excluded_fold_is_still_reported_not_hidden(fake_engine):
    out = wf.walk_forward(BASE, {"n_holdings": [10]}, metric="sharpe", is_years=3.0, oos_years=1.0)
    stubs = [w for w in out["windows"] if w["truncated"]]
    assert stubs, "expected a truncated fold"
    assert all("oos_days" in w for w in out["windows"])
    assert out["warnings"] and "excluded" in out["warnings"][0]
    assert str(stubs[0]["oos_days"]) in out["warnings"][0]


def test_full_folds_are_all_kept(fake_engine):
    """No silent shrinking of the evidence base when nothing is truncated.

    end is chosen to land exactly on a fold boundary: with is_years=3 (1095d) and oos_years=1
    (365d) from 2015-01-01, the folds close on 2018-12-31 and 2019-12-31, so 2019-12-31 clips
    nothing. Picking a date that happens to clip would make this test skip itself, which proves
    nothing (the #853 lesson).
    """
    base = {**BASE, "end": "2019-12-31"}
    out = wf.walk_forward(base, {"n_holdings": [10]}, metric="sharpe", is_years=3.0, oos_years=1.0)
    assert out["n_windows"] >= 2, out["n_windows"]
    assert not any(w["truncated"] for w in out["windows"]), (
        f"expected no clipped folds, got {[w['oos_days'] for w in out['windows']]}")
    assert out["n_windows_scored"] == out["n_windows"]
    assert out["warnings"] == []


def test_all_stub_folds_is_flagged_loudly_rather_than_returning_nothing(fake_engine):
    """Degenerate case: a range too short to walk forward at all."""
    base = {**BASE, "start": "2015-01-01", "end": "2018-02-01"}
    out = wf.walk_forward(base, {"n_holdings": [10]}, metric="sharpe", is_years=3.0, oos_years=1.0)
    if out["n_windows"] == 0:
        pytest.skip("no windows produced for this range")
    if all(w["truncated"] for w in out["windows"]):
        assert out["n_windows_scored"] == out["n_windows"]
        assert any("EVERY out-of-sample fold" in w for w in out["warnings"])
