"""iter-23 #219, endpoint level: POST /api/backtests/batch must refuse resolve-affecting grid keys.

The iter-22 fix (#210) made stop grids honest by grouping resolves on `_resolve_key`, but every
OTHER resolve-affecting key — rank_by / rank_blend / universe.* / entry_filters / start / end /
benchmark / data_source / regime_filter.* — still silently reused the base's panels and labelled
the results as though the parameter had varied (measured: regime grid 0.2289 vs 0.2350 direct).
The docstring said "don't grid these", but an API consumer cannot read a docstring. These tests
pin the enforced allowlist: unsafe keys 400 BEFORE the base resolve is paid for; verified sim-side
keys keep working, sharing one resolve.

Same conventions as test_batch_endpoint_stop.py: handler called directly, resolve/run_backtest
stubbed — this asserts dispatch/refusal logic, not engine numbers.
"""
import pytest
from fastapi import HTTPException

import app.main as main
from app.main import BatchIn, backtests_batch, _unsafe_grid_keys


class _FakeRS:
    def __init__(self, cfg):
        pass


class _FakeRes:
    def __init__(self):
        self._d = {"summary": {"cagr": 0.1}, "warnings": []}

    def model_dump(self):
        return self._d


class _Recorder:
    def __init__(self):
        self.resolved, self.simmed = [], []


@pytest.fixture
def client(monkeypatch):
    rec = _Recorder()

    def fake_resolve(cfg):
        d = cfg.model_dump() if hasattr(cfg, "model_dump") else cfg
        rec.resolved.append(d)
        return _FakeRS(d)

    def fake_run(cfg, rs=None):
        rec.simmed.append(cfg)
        return _FakeRes()

    monkeypatch.setattr(main, "resolve_with_warmup", fake_resolve)
    monkeypatch.setattr(main, "run_backtest", fake_run)
    return rec


def _post(grid):
    base = {"name": "t", "start": "2020-01-01"}
    return backtests_batch(BatchIn(base_config=base, grid=grid, save=False))


# ── refusals: the #219 leak classes ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("key", [
    "regime_filter.enabled",       # warmup pad sized at resolve — the measured iter-22 leak
    "regime_filter.ma_period",
    "regime_filter.below_exposure",
    "rank_by",                     # rank panel built at resolve
    "rank_blend",
    "universe.filters",            # entry mask built at resolve
    "universe.index",
    "entry_filters",
    "start", "end", "benchmark", "data_source",
    "factor_timing.ma_period",     # unverified for batch — refused until proven sim-side
])
def test_refuses_resolve_affecting_key(client, key):
    with pytest.raises(HTTPException) as exc:
        _post({key: [1, 2]})
    assert exc.value.status_code == 400
    assert key in str(exc.value.detail)
    assert "#219" in str(exc.value.detail)


def test_refusal_names_all_offenders_not_the_safe_keys(client):
    with pytest.raises(HTTPException) as exc:
        _post({"n_holdings": [10, 20], "rank_by": ["roc252"], "regime_filter.enabled": [True]})
    detail = str(exc.value.detail)
    assert "rank_by" in detail and "regime_filter.enabled" in detail
    assert "'n_holdings'" not in detail.split("Safe grid keys")[0]  # offender list excludes safe keys


def test_refusal_costs_no_resolve(client):
    """The 400 must fire BEFORE the base resolve is paid for."""
    with pytest.raises(HTTPException):
        _post({"rank_by": ["roc252", "roc126"]})
    assert client.resolved == []


# ── the allowlist: verified sim-side keys keep working ────────────────────────────────────────
def test_safe_scalar_keys_share_one_resolve(client):
    body = _post({"n_holdings": [5, 10], "rank_order": ["asc", "desc"], "capital": [100000.0]})
    assert body["n"] == 4
    assert body["n_resolves"] == 1
    assert all("error" not in r for r in body["results"])


def test_take_profit_prefix_allowed(client):
    body = _post({"take_profit.type": ["pct"], "take_profit.value": [0.2, 0.3]})
    assert body["n"] == 2
    assert all("error" not in r for r in body["results"])


def test_empty_grid_untouched(client):
    body = _post({})
    assert body["n"] == 1 and body["n_resolves"] == 1


# ── the helper itself ─────────────────────────────────────────────────────────────────────────
def test_unsafe_grid_keys_is_sorted_and_exact():
    assert _unsafe_grid_keys(["rank_by", "n_holdings", "benchmark"]) == ["benchmark", "rank_by"]
    assert _unsafe_grid_keys(["stop_loss.mult", "take_profit.value", "rebalance"]) == []
