"""The three defects filed against /api/rotation at iter-23 (to-do #250).

1. a single-sleeve fixed-weight call (weights=[1.0]) returned 400
2. calmar read 0 in every summary
3. a valid multi-sleeve call intermittently 400d, then worked on retry

(2) turned out not to be a zero at all: `calmar` was never a field on Summary. The iter-23 research
harnesses read `s.get("calmar")` and printed `(... or 0)`, so an absent metric rendered as a zero
metric. (3) reproduced as a real race on the shared read-only DuckDB connection - see the concurrency
test at the bottom, which fails 11-of-12 threads against the pre-fix code.
"""
import threading

import numpy as np
import pandas as pd
import pytest

from windfall.engine import metrics
from windfall.engine.rotation import run_rotation


# ── (1) single-sleeve fixed weight ───────────────────────────────────────────────────────────
def test_rotation_still_requires_two_sleeves_to_ROTATE():
    """The floor is right for rotation mode - there is nothing to rotate between with one sleeve."""
    with pytest.raises(ValueError, match="at least 2 sleeves"):
        run_rotation([{"name": "only"}], weights=None)


def test_single_sleeve_guard_no_longer_rejects_a_fixed_weight_call():
    """The narrow assertion: the sleeve-count floor is not applied in fixed-weight mode.

    Deliberately tolerant of downstream data/config failures - it pins the guard alone. The AC
    ("returns 200 with a valid summary") is proved END TO END by the test below, on real data;
    this one exists so the guard has a check that still runs in a bare environment with no
    Trendlyne store. Keeping only this one would be the weaker choice: the API wraps run_rotation
    in a blanket `except Exception -> HTTPException(400)`, so any latent single-sleeve failure
    downstream would still surface as the very 400 this AC is about, and a swallow-everything
    test would never see it. (Raised by the Stage 4.7 verifier on the first version of this file.)
    """
    try:
        run_rotation([{"name": "solo"}], weights=[1.0])
    except ValueError as exc:
        assert "at least 2 sleeves" not in str(exc), f"still rejected by the sleeve-count floor: {exc}"
    except Exception:  # noqa: BLE001 — downstream data failures are the other test's job
        pass


def test_single_sleeve_fixed_weight_produces_a_real_summary_end_to_end():
    """The actual AC: a single-sleeve weights=[1.0] call completes and returns a usable summary.

    Uses the same real-data sleeve as tests/test_rotation.py rather than a stub, so this exercises
    the whole path the API calls - resolve, backtest, NAV alignment, turnover, summary - with one
    sleeve, which is where a lurking multi-sleeve assumption would surface.
    """
    ts = pytest.importorskip("windfall.data.trendlyne_store")
    if not ts.available():
        pytest.skip("trendlyne.duckdb not present in this environment")

    from tests.test_rotation import SLEEVE_A

    out = run_rotation([SLEEVE_A], weights=[1.0])

    assert out["equity_curve"] and len(out["equity_curve"]) > 100
    s = out["summary"]
    assert pd.notna(s["cagr"]) and pd.notna(s["max_drawdown"])
    assert np.isfinite(s["cagr"]) and np.isfinite(s["calmar"])
    assert 0.0 <= s["exposure"] <= 1.0 + 1e-9
    assert len(out["sleeves"]) == 1
    assert out["config"]["mode"] == "fixed-weight"
    assert out["config"]["weights"] == [1.0]
    assert out["allocations"], "a fixed-weight book must still record its rebalances"


def test_empty_sleeve_list_is_still_rejected():
    with pytest.raises(ValueError, match="at least one sleeve"):
        run_rotation([], weights=[])


# ── (2) calmar ───────────────────────────────────────────────────────────────────────────────
def _nav(values):
    idx = pd.bdate_range("2020-01-01", periods=len(values))
    return pd.Series([float(v) for v in values], index=idx)


def test_calmar_is_computed_not_zero():
    """A curve that rises overall through a real drawdown must report a non-zero calmar."""
    nav = _nav([100, 120, 90, 110, 150, 140, 180])
    s = metrics.compute_summary(nav, [], None, years=1.0, annual_turnover=0.0, exposure=1.0)
    assert s.max_drawdown < 0
    assert s.calmar != 0.0
    assert s.calmar == pytest.approx(s.cagr / abs(s.max_drawdown), rel=1e-3)


def test_calmar_is_zero_when_there_is_no_drawdown_not_infinite():
    """Undefined, not infinite: a monotonic curve is too short to rate, never risk-free."""
    s = metrics.compute_summary(_nav(range(100, 120)), [], None, 1.0, 0.0, 1.0)
    assert s.max_drawdown == 0.0
    assert s.calmar == 0.0
    assert np.isfinite(s.calmar)


def test_calmar_is_negative_for_a_losing_strategy():
    """Sign follows CAGR - a loss-making book must not look good on a drawdown-adjusted metric."""
    s = metrics.compute_summary(_nav([100, 90, 80, 70, 60]), [], None, 1.0, 0.0, 1.0)
    assert s.cagr < 0 and s.calmar < 0


def test_calmar_is_serialised_in_the_summary_contract():
    """The research harnesses read it via s.get('calmar') off the JSON - it must survive dump."""
    s = metrics.compute_summary(_nav([100, 120, 90, 150]), [], None, 1.0, 0.0, 1.0)
    assert "calmar" in s.model_dump()


# ── (3) the concurrency race behind the transient 400 ────────────────────────────────────────
def test_shared_trendlyne_connection_is_safe_under_concurrent_first_calls():
    """12 threads onto a cold cache. Pre-fix this raised on 11 of them:

        Binder Error: Failed to attach database: database with name "bc" already exists

    lru_cache guards its dict, not the wrapped call, so every thread ran the check-then-ATTACH.
    """
    ts = pytest.importorskip("windfall.data.trendlyne_store")
    if not ts.available():
        pytest.skip("trendlyne.duckdb not present in this environment")

    n = 12
    barrier = threading.Barrier(n)
    errors: list[BaseException] = []

    def worker():
        barrier.wait()
        try:
            ts._con().execute("SELECT 1").fetchone()
        except BaseException as exc:  # noqa: BLE001 — collect, assert in the main thread
            errors.append(exc)

    ts._con.cache_clear()
    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"{len(errors)} of {n} concurrent callers failed: {errors[0]!r}"
