"""iter-22 #210: the batch endpoint must not share one resolve across differing ATR stop panels.

resolve() builds the ATR stop panel ONLY when the config it is handed already asks for an
atr/trailing stop, and sizes it by atr_period. /api/backtests/batch resolved once from base_config
and reused that ResolvedStrategy for every combo, so gridding stop_loss.type=[trailing] off a
no-stop base left rs.atr_stop=None -> the trailing branch in check_exit never fired -> results came
back byte-identical to no-stop while labelled as a trailing sweep. Measured 2026-07-16: DVM_user
trailing 3x reported CAGR 0.3357 (the no-stop number); resolved correctly it is 0.0631.

_resolve_key groups combos so each distinct panel gets its own resolve.
"""
from app.main import _resolve_key


def _cfg(**stop):
    return {"name": "t", "stop_loss": stop} if stop else {"name": "t"}


# ── the regression: a stop that needs a panel must not share the no-stop resolve ──────────────
def test_trailing_does_not_share_resolve_with_none():
    assert _resolve_key(_cfg(type="trailing", mult=3.0, atr_period=14)) != _resolve_key(_cfg(type="none"))


def test_atr_does_not_share_resolve_with_none():
    assert _resolve_key(_cfg(type="atr", mult=2.0, atr_period=14)) != _resolve_key(_cfg(type="none"))


def test_differing_atr_period_does_not_share_resolve():
    """The panel is sized by atr_period — a 14-day panel cannot serve a 21-day stop."""
    a = _resolve_key(_cfg(type="trailing", mult=3.0, atr_period=14))
    b = _resolve_key(_cfg(type="trailing", mult=3.0, atr_period=21))
    assert a != b


# ── the optimisation must survive: genuinely sim-side params still share one resolve ──────────
def test_mult_is_sim_side_and_shares_one_resolve():
    a = _resolve_key(_cfg(type="trailing", mult=2.0, atr_period=14))
    b = _resolve_key(_cfg(type="trailing", mult=5.0, atr_period=14))
    assert a == b


def test_pct_needs_no_panel_and_shares_the_none_resolve():
    """_stop_target's pct branch reads no ATR, so pct and none can share a ResolvedStrategy."""
    assert _resolve_key(_cfg(type="pct", value=0.2)) == _resolve_key(_cfg(type="none"))


def test_pct_value_is_sim_side():
    assert _resolve_key(_cfg(type="pct", value=0.15)) == _resolve_key(_cfg(type="pct", value=0.30))


def test_missing_stop_loss_block_is_treated_as_no_panel():
    assert _resolve_key(_cfg()) == _resolve_key(_cfg(type="none"))


# ── grouping arithmetic: how many resolves a real sweep costs ─────────────────────────────────
def test_stop_type_sweep_groups_into_two_resolves():
    keys = {_resolve_key(_cfg(type=t, mult=3.0, atr_period=14)) for t in ("none", "pct", "atr", "trailing")}
    assert len(keys) == 3          # {no-panel (none+pct), atr, trailing}


def test_width_only_sweep_costs_a_single_resolve():
    keys = {_resolve_key(_cfg(type="trailing", mult=m, atr_period=14)) for m in (2.0, 3.0, 4.0, 5.0)}
    assert len(keys) == 1
