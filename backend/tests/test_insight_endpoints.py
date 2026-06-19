"""iter-7: surveillance-CSV export (#19) + cost-sensitivity & A/B compare endpoints (#16)."""
from windfall.data import surveillance
from windfall.signals_live.generate import signals_to_csv

# Same synthetic-universe config the cost tests use (conftest seeds nifty500 = AAA..FFF).
BASE = {
    "name": "iter7_base",
    "universe": {"index": "nifty500", "filters": []},
    "entry_filters": ["close > sma50"],
    "rank_by": "roc21", "rank_order": "desc",
    "n_holdings": 3, "weighting": "equal", "rebalance": "weekly", "entry_fill": "next_open",
    "stop_loss": {"type": "none"}, "take_profit": {"type": "none"},
    "start": "2018-06-01", "end": "2020-12-31", "benchmark": "NIFTY500",
}


# ── #19: surveillance flag reaches the export CSV ────────────────────────────
def test_signals_csv_carries_surveillance_flag(monkeypatch):
    monkeypatch.setattr(surveillance, "latest_flags",
                        lambda: {"flags": {"ABC": [{"list": "ASM", "stage": "II", "desc": ""}]}})
    run = {"signals": [
        {"ticker": "ABC.NS", "action": "buy", "weight": 0.5, "last_close": 100.0},
        {"ticker": "XYZ.NS", "action": "buy", "weight": 0.5, "last_close": 50.0},
    ]}
    out = surveillance.annotate_signals(run)
    csv_text = signals_to_csv(out)
    header = csv_text.splitlines()[0]
    assert "surveillance" in header.split(",")
    abc = next(l for l in csv_text.splitlines() if l.startswith("ABC.NS"))
    assert "ASM" in abc                      # surveilled name carries the flag in its row
    xyz = next(l for l in csv_text.splitlines() if l.startswith("XYZ.NS"))
    assert xyz.count("ASM") == 0             # un-surveilled name has it blank


# ── #16a: cost-sensitivity endpoint ─────────────────────────────────────────
def test_cost_sensitivity_monotonic_and_scaled():
    from app.main import CostSensitivityIn, backtests_cost_sensitivity
    out = backtests_cost_sensitivity(CostSensitivityIn(config=BASE))
    runs = out["runs"]
    assert [r["cost_multiplier"] for r in runs] == [0.0, 1.0, 2.0]
    # net total return can only fall (or tie) as modelled costs scale up
    trs = [r["summary"]["total_return"] for r in runs]
    assert trs[0] >= trs[1] - 1e-9 >= trs[2] - 2e-9
    # costs are scaled off the resolved base, not zeroed/duplicated
    assert runs[0]["costs_bps"] == {"brokerage": 0.0, "stt": 0.0, "slippage": 0.0}
    assert runs[2]["costs_bps"]["stt"] == 2 * out["base_costs_bps"]["stt"]
    assert all(k in runs[0]["summary"] for k in ("cagr", "sharpe", "annual_turnover"))


def test_cost_sensitivity_custom_multipliers():
    from app.main import CostSensitivityIn, backtests_cost_sensitivity
    out = backtests_cost_sensitivity(CostSensitivityIn(config=BASE, multipliers=[1.0, 3.0]))
    assert [r["cost_multiplier"] for r in out["runs"]] == [1.0, 3.0]


# ── #16b: A/B compare endpoint ──────────────────────────────────────────────
def test_compare_identical_configs_match():
    from app.main import CompareIn, backtests_compare
    out = backtests_compare(CompareIn(config_a=BASE, config_b=BASE))
    assert set(out) == {"a", "b"}
    assert out["a"]["summary"]["total_return"] == out["b"]["summary"]["total_return"]
    assert out["a"]["equity_curve"] and out["b"]["equity_curve"]          # curves present
    assert "summary" in out["a"] and "name" in out["b"]


def test_compare_distinguishes_strategies():
    from app.main import CompareIn, backtests_compare
    b_slow = {**BASE, "rebalance": "monthly"}     # same selection, slower rotation
    out = backtests_compare(CompareIn(config_a=BASE, config_b=b_slow))
    # weekly (a) rotates the book more than monthly (b) -> higher annual turnover; both ran cleanly
    assert out["a"]["summary"]["annual_turnover"] >= out["b"]["summary"]["annual_turnover"] - 1e-9
    assert isinstance(out["a"]["summary"]["n_trades"], int)
