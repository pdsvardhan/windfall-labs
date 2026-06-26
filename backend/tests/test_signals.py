"""Live signal generation (incl. regime-enabled configs, which exercise benchmark alignment)."""
from windfall.signals_live import generate_blend_signals, generate_signals
from windfall.signals_live.generate import signals_to_csv

BASE = {
    "name": "sig_test",
    "universe": {"index": "nifty500", "filters": []},
    "entry_filters": ["close > sma50"],
    "rank_by": "roc21", "rank_order": "desc",
    "n_holdings": 3, "rebalance": "weekly",
    "stop_loss": {"type": "atr", "mult": 2.0},
    "start": "2018-06-01", "benchmark": "NIFTY500",
}


def test_signals_basic_shape():
    out = generate_signals(dict(BASE))
    assert out["as_of"] is not None
    for s in out["signals"]:
        assert s["action"] in ("buy", "hold", "sell")
        assert "weight" in s


def test_signals_warn_when_no_stop():
    out = generate_signals({**BASE, "stop_loss": {"type": "none"}})
    assert any("no stop" in w.lower() for w in out["warnings"])


def test_signals_with_regime_filter_reports_state():
    out = generate_signals({**BASE, "regime_filter": {"enabled": True, "ma_period": 50}})
    assert out["regime"] is not None
    assert "index_above_ma" in out["regime"]


# ── blend live-signals (adr-035 70/30 deployable artifact) ───────────────────────────────────────
SLEEVE_A = {**BASE, "name": "MOM", "rank_by": "roc63", "n_holdings": 5}
SLEEVE_B = {**BASE, "name": "LV", "rank_by": "atr14 / close", "rank_order": "asc", "n_holdings": 5}


def test_blend_signals_basic_shape_and_actions():
    out = generate_blend_signals([SLEEVE_A, SLEEVE_B], [0.7, 0.3], name="70/30")
    assert out["as_of"] is not None
    assert out["blend_weights"] == [0.7, 0.3]
    assert len(out["sleeves"]) == 2
    for s in out["signals"]:
        assert s["action"] in ("buy", "hold", "sell")
        assert "weight" in s and "blend_sleeves" in s


def test_blend_signals_weights_sum_to_invested_fraction():
    """The combined book's held weights must sum to ~the invested fraction (<=1), never exceed 1."""
    out = generate_blend_signals([SLEEVE_A, SLEEVE_B], [0.7, 0.3])
    held = sum(s["weight"] for s in out["signals"] if s["action"] != "sell")
    assert held <= 1.0 + 1e-6
    assert abs(held - out["invested_fraction"]) < 1e-6


def test_blend_signals_shared_name_sums_contributions():
    """A name held by BOTH sleeves must carry contributions from both (provenance shows 2 sleeves)."""
    out = generate_blend_signals([SLEEVE_A, SLEEVE_A], [0.5, 0.5], name="dup")
    # identical sleeves -> every held name is in both -> blend_sleeves lists 2 entries
    held = [s for s in out["signals"] if s["action"] != "sell"]
    assert held and all(s["blend_sleeves"].count(":") == 2 for s in held)


def test_blend_signals_validates_inputs():
    import pytest
    with pytest.raises(Exception):
        generate_blend_signals([SLEEVE_A], [1.0])               # needs >=2 sleeves
    with pytest.raises(Exception):
        generate_blend_signals([SLEEVE_A, SLEEVE_B], [0.7])     # weights length mismatch


def test_blend_signals_export_to_csv_has_provenance_column():
    out = generate_blend_signals([SLEEVE_A, SLEEVE_B], [0.7, 0.3])
    csv = signals_to_csv(out)
    assert "blend_sleeves" in csv.splitlines()[0]
