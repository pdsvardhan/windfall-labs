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
    Cost-basis view would say 100,000 - 20,000 = 80,000 available. True cash is 76,000.
    """
    monkeypatch.setattr(rebalance, "list_positions", lambda sid: [
        {"status": "closed", "entry": 100.0, "shares": 100.0, "exit": 60.0},
        {"status": "open", "entry": 200.0, "shares": 100.0, "exit": None},
    ])
    assert rebalance.available_cash(SID, 100000.0) == pytest.approx(76000.0)


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


def test_unitization_is_flat_across_a_contribution_and_a_withdrawal():
    """Units issued on money in and redeemed on money out, both at the prevailing NAV per unit.

    Mirrors the loop in book_equity, including how NAV actually responds to a cash flow: NAV is
    (holdings at market) + (base - invested), so contributed cash raises NAV by exactly itself —
    it does not scale the existing gain. A book holding 110,000 of stock bought for 100,000 is up
    10%; adding 400,000 of cash must leave it up 10%, and taking that 400,000 straight back out
    must too. The issue-only guard skipped the withdrawal, leaving units inflated against an
    unchanged NAV and reporting the book at roughly -79%.
    """
    invested, holdings_value = 100000.0, 110000.0
    base = units = 100000.0

    def nav(b):
        return holdings_value + (b - invested)

    assert nav(base) / units - 1 == pytest.approx(0.10)

    for new_base in (500000.0, 100000.0):
        flow = new_base - base
        units += flow / (nav(base) / units)
        base = new_base
        assert nav(base) / units - 1 == pytest.approx(0.10), "a cash flow moved the return"

    assert units == pytest.approx(100000.0), "units must return to their pre-flow count"


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
