"""Live signal generation (incl. regime-enabled configs, which exercise benchmark alignment)."""
from windfall.signals_live import generate_signals

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
