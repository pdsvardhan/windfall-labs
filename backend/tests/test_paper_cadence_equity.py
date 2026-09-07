"""Unit tests for the iter-171 paper-book arithmetic: rebalance cadence, the cash guard, and the
NAV curve's unitization across a notional change.

These exist because iter-171's verifier caught a one-sided unitization guard AFTER the code had been
deployed: a notional that stepped up and back down left units inflated against an unchanged NAV and
reported every book at roughly -79% while all eight were profitable. The arithmetic here is pure and
cheap to test; three assertions would have caught it before it shipped.
"""
from __future__ import annotations

import datetime as dt

import pytest

from windfall.paper import book, equity, rebalance

SID = "TEST_CADENCE"


# ── cadence (item 1231) ──────────────────────────────────────────────────────

def test_period_key_monthly_same_month_is_one_period():
    k = rebalance._period_key
    assert k(dt.date(2026, 9, 1), "monthly") == k(dt.date(2026, 9, 30), "monthly")
    assert k(dt.date(2026, 8, 31), "monthly") != k(dt.date(2026, 9, 1), "monthly")


def test_period_key_weekly_splits_by_iso_week():
    k = rebalance._period_key
    # Fri 4 Sep and Mon 7 Sep 2026 are different ISO weeks — a weekly book is due again.
    assert k(dt.date(2026, 9, 4), "weekly") != k(dt.date(2026, 9, 7), "weekly")
    # Mon 31 Aug and Sun 6 Sep are the SAME ISO week — it is not due twice.
    assert k(dt.date(2026, 8, 31), "weekly") == k(dt.date(2026, 9, 6), "weekly")


def test_period_key_quarterly_crosses_year_boundary():
    k = rebalance._period_key
    assert k(dt.date(2026, 12, 28), "quarterly") != k(dt.date(2027, 1, 3), "quarterly")
    assert k(dt.date(2026, 7, 1), "quarterly") == k(dt.date(2026, 9, 30), "quarterly")


def test_unknown_cadence_falls_back_to_monthly():
    k = rebalance._period_key
    assert k(dt.date(2026, 9, 4), "fortnightly") == k(dt.date(2026, 9, 4), "monthly")


def test_is_due_true_when_never_run(monkeypatch):
    monkeypatch.setattr(rebalance, "_cadence", lambda e: "monthly")
    monkeypatch.setattr(rebalance, "_last_run", lambda sid: None)
    due, cadence = rebalance.is_due({"sid": SID, "kind": "saved"}, dt.date(2026, 9, 4))
    assert due is True and cadence == "monthly"


def test_is_due_false_inside_the_same_period(monkeypatch):
    monkeypatch.setattr(rebalance, "_cadence", lambda e: "monthly")
    monkeypatch.setattr(rebalance, "_last_run", lambda sid: dt.date(2026, 9, 1))
    due, _ = rebalance.is_due({"sid": SID, "kind": "saved"}, dt.date(2026, 9, 4))
    assert due is False


def test_is_due_catches_up_a_missed_period(monkeypatch):
    """A run missed to a holiday or a failed cron is caught up, not skipped for the whole period."""
    monkeypatch.setattr(rebalance, "_cadence", lambda e: "monthly")
    monkeypatch.setattr(rebalance, "_last_run", lambda sid: dt.date(2026, 7, 1))
    due, _ = rebalance.is_due({"sid": SID, "kind": "saved"}, dt.date(2026, 9, 4))
    assert due is True


# ── cash guard (item 1235) ───────────────────────────────────────────────────

def test_available_cash_counts_realised_losses(monkeypatch):
    """Sizing off notional-minus-open-cost ignores realised losses and overstates capacity.

    Book: bought 10,000, sold it for 6,000 (a 4,000 realised loss), and holds 20,000 more at cost.
    Cost-basis view would say 100,000 - 20,000 = 80,000 available. Gross of costs it is 76,000.

    Since #864 the balance is also NET of modelled costs, so the expectation is derived from the
    cost constants rather than written as a number — if the cost model changes, this test should
    follow it instead of failing. Only costs actually PAID are charged: both buys pay entry cost,
    the closed position pays its sell cost, and the open position does not (it has not sold).
    """
    monkeypatch.setattr(rebalance, "list_positions", lambda sid: [
        {"status": "closed", "entry": 100.0, "shares": 100.0, "exit": 60.0},
        {"status": "open", "entry": 200.0, "shares": 100.0, "exit": None},
    ])
    costs = (10_000 * rebalance.NSE_BUY_RATE                       # buy the closed position
             + 20_000 * rebalance.NSE_BUY_RATE                     # buy the open position
             + 6_000 * rebalance.NSE_SELL_RATE + rebalance.DP_FLAT)  # sell the closed one
    assert rebalance.available_cash(SID, 100000.0) == pytest.approx(76_000.0 - costs)
    assert 0 < costs < 500, f"modelled costs on Rs36k of turnover look wrong: {costs}"


def test_available_cash_does_not_charge_an_unsold_position_a_sell_cost(monkeypatch):
    """#864: a cash balance pays for trades that happened, not for one the book might make.

    This is the difference from book._net_pnl, which marks to market and so models the exit cost
    of a sale that has not occurred. Charging it here would understate spendable cash and could
    make a rebalance skip a name it can actually afford.
    """
    monkeypatch.setattr(rebalance, "list_positions", lambda sid: [
        {"status": "open", "entry": 100.0, "shares": 100.0, "exit": None},
    ])
    expected = 100_000.0 - 10_000.0 - 10_000.0 * rebalance.NSE_BUY_RATE
    assert rebalance.available_cash(SID, 100_000.0) == pytest.approx(expected)


def test_available_cash_holds_back_pending_commitments(monkeypatch):
    monkeypatch.setattr(rebalance, "list_positions", lambda sid: [
        {"status": "pending", "entry": None, "shares": None, "exit": None,
         "planned_capital": 5000.0},
    ])
    assert rebalance.available_cash(SID, 100000.0) == pytest.approx(95000.0)


def test_available_cash_of_an_untouched_book_is_its_notional(monkeypatch):
    monkeypatch.setattr(rebalance, "list_positions", lambda sid: [])
    assert rebalance.available_cash(SID, 100000.0) == pytest.approx(100000.0)


# ── notional steps + unitization (items 1229, 1236) ──────────────────────────

def _steps(rows, since="2026-06-29"):
    """Drive _notional_steps off a fake run log."""
    class _Con:
        def execute(self, *_a, **_k):
            return self

        def fetchall(self):
            return rows

        def close(self):
            pass

    import windfall.store_meta as sm
    real = sm._init
    sm._init = lambda: _Con()
    try:
        return equity._notional_steps("ANY", since)
    finally:
        sm._init = real


def test_notional_steps_no_runs_is_a_single_legacy_step():
    assert _steps([]) == [("2026-06-29", equity.LEGACY_NOTIONAL)]


def test_notional_steps_ignores_a_run_that_changed_nothing():
    assert _steps([(dt.date(2026, 8, 1), 100000.0)]) == [("2026-06-29", 100000.0)]


def test_notional_steps_records_a_real_change():
    assert _steps([(dt.date(2026, 10, 1), 500000.0)]) == [
        ("2026-06-29", 100000.0), ("2026-10-01", 500000.0)]


def test_notional_steps_collapses_two_runs_on_one_day():
    """ran_at is a DATE. An aborted step-up leaves a Rs5L run and a Rs1L correction on the same day;
    only the LAST one is that day's notional, or a phantom step corrupts the whole curve."""
    assert _steps([(dt.date(2026, 9, 4), 500000.0),
                   (dt.date(2026, 9, 4), 100000.0)]) == [("2026-06-29", 100000.0)]


DATES = ["2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02", "2026-07-03"]


def _run_book_equity(monkeypatch, steps):
    """Drive the REAL book_equity() over one deterministic book, with a chosen notional history.

    One position: 100 shares bought at 100 (Rs10,000 of a Rs1L book) on day 0, still open, with the
    price walking 100 -> 104. Everything book_equity touches is pinned, so the only thing under test
    is its own loop.
    """
    import pandas as pd

    positions = [{
        "id": "p1", "strategy_id": SID, "ticker": "AAA", "status": "open",
        "entry_date": DATES[0], "entry": 100.0, "shares": 100.0,
        "exit": None, "exit_date": None, "last_price": 104.0, "last_date": DATES[-1],
    }]
    panel = pd.DataFrame(
        {"AAA": [100.0, 101.0, 102.0, 103.0, 104.0]},
        index=pd.to_datetime(DATES))

    monkeypatch.setattr(equity, "list_positions", lambda *a, **k: positions)
    monkeypatch.setattr(equity.ts, "adjusted_close_panel", lambda *a, **k: panel)
    monkeypatch.setattr(equity, "_with_bhavcopy_fallback", lambda p, t, s: p)
    monkeypatch.setattr(equity.ts, "benchmark_series",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no benchmark")))
    monkeypatch.setattr(equity, "_notional_steps", lambda sid, since: steps)
    out = equity.book_equity()
    return dict(out["books"][SID]["points"])


def test_a_contribution_does_not_move_the_return(monkeypatch):
    """Money arriving is not a gain. The point ON the step date must be what it would have been."""
    flat = _run_book_equity(monkeypatch, [(DATES[0], 100000.0)])
    up = _run_book_equity(monkeypatch, [(DATES[0], 100000.0), (DATES[2], 500000.0)])
    assert up[DATES[2]] == pytest.approx(flat[DATES[2]], abs=1e-9)
    # ...and only afterwards does the idle cash dilute it, which is a real drag, not a jump.
    assert up[DATES[4]] < flat[DATES[4]]


def test_a_withdrawal_does_not_move_the_return(monkeypatch):
    """The half the round-1 bug skipped. Removing money must not move the return either.

    Compared against the SAME history with only the final flow removed — not against the unstepped
    book, which has legitimately diverged by then. Under the one-sided `if flow > 0` guard the units
    stay inflated here and this book reads about -79% instead of a couple of percent.
    """
    up_only = _run_book_equity(monkeypatch, [(DATES[0], 100000.0), (DATES[1], 500000.0)])
    up_then_down = _run_book_equity(
        monkeypatch, [(DATES[0], 100000.0), (DATES[1], 500000.0), (DATES[3], 100000.0)])
    assert up_then_down[DATES[3]] == pytest.approx(up_only[DATES[3]], abs=1e-9)
    assert up_then_down[DATES[3]] > -0.5, "units left inflated across the withdrawal"


def test_book_with_no_notional_change_returns_the_plain_nav(monkeypatch):
    """Sanity anchor: 100 shares 100 -> 104 on a Rs1L book is +Rs400, i.e. +0.4%."""
    flat = _run_book_equity(monkeypatch, [(DATES[0], 100000.0)])
    assert flat[DATES[0]] == pytest.approx(0.0)
    assert flat[DATES[4]] == pytest.approx(400.0 / 100000.0)


def test_max_drawdown_on_a_nav_series():
    assert equity._max_drawdown([1.0, 1.2, 0.9, 1.1]) == pytest.approx(0.9 / 1.2 - 1.0)
    assert equity._max_drawdown([1.0, 1.1, 1.2]) == pytest.approx(0.0)
    assert equity._max_drawdown([]) == 0.0


# ── mark reporting (item 1232) ───────────────────────────────────────────────

def test_mark_reports_positions_it_could_not_price(monkeypatch):
    """An unpriceable OPEN holding is counted and named, never silently skipped."""
    monkeypatch.setattr(book, "_latest_close", lambda t: (None, None))
    monkeypatch.setattr(book, "fill_pending", lambda: {"pending_filled": 0, "pending_voided": 0})
    pid = None
    monkeypatch.setattr(book, "_next_open", lambda t, after: (None, None))
    # seed one open position with a price, then blind the mark
    monkeypatch.setattr(book, "_latest_close", lambda t: (dt.date.today(), 100.0))
    pid = book.commit_signal(SID, {"ticker": "ZZZ", "weight": 1.0}, 10000.0)
    assert pid
    monkeypatch.setattr(book, "_latest_close", lambda t: (None, None))
    out = book.mark_to_market()
    assert out["unpriced"] >= 1
    assert "ZZZ" in out["unpriced_tickers"]
