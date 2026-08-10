"""iter-147 item 935 (todo #248): rebalance entries fill at the NEXT session's open.

Unit tests — price lookups are monkeypatched so these run anywhere (no Trendlyne store needed).
The one integration-shaped case (_next_open weekend skip) feeds a synthetic panel through the
real filter, so the strictly-after logic is tested, not a mock of it.
"""
import datetime as dt

import pandas as pd
import pytest

from windfall.paper import book, rebalance

SID = "TEST_NEXTOPEN"


@pytest.fixture(autouse=True)
def clean_book():
    book.delete_positions(SID)
    yield
    book.delete_positions(SID)


def _pending(ticker="AAA", cap=20000.0, stop=90.0, target=150.0, weight=0.5):
    return book.commit_pending_signal(
        SID, {"ticker": ticker, "stop": stop, "target": target, "weight": weight}, cap)


def _row(pid):
    return next(p for p in book.list_positions(SID) if p["id"] == pid)


def test_commit_pending_has_no_entry_price():
    pid = _pending()
    p = _row(pid)
    assert p["status"] == "pending"
    assert p["entry"] is None and p["shares"] is None and p["entry_date"] is None
    assert p["planned_capital"] == 20000.0


def test_fill_prices_at_next_open(monkeypatch):
    pid = _pending(cap=20000.0)
    fill_day = dt.date.today() + dt.timedelta(days=3)
    monkeypatch.setattr(book, "_next_open", lambda t, after: (fill_day, 101.5))
    out = book.fill_pending()
    assert out == {"pending_filled": 1, "pending_voided": 0}
    p = _row(pid)
    assert p["status"] == "open"
    assert p["entry"] == 101.5
    assert p["entry_date"] == str(fill_day)
    assert p["shares"] == 197  # floor(20000 / 101.5)


def test_next_open_skips_weekend_bars(monkeypatch):
    # commit lands on a Saturday (the real rebalance cron fired Sat 1 Aug 2026): Friday's bar
    # must NOT fill it — the first bar strictly after is Monday's.
    sat = dt.date(2026, 8, 1)
    idx = pd.DatetimeIndex([dt.datetime(2026, 7, 31), dt.datetime(2026, 8, 3)])
    panel = pd.DataFrame({"AAA": [99.0, 102.0]}, index=idx)
    monkeypatch.setattr(book.ts, "adjusted_close_panel", lambda *a, **k: panel)
    d, px = book._next_open("AAA", sat)
    assert d == dt.date(2026, 8, 3)
    assert px == 102.0


def test_unfillable_granularity_voids(monkeypatch):
    pid = _pending(cap=50.0)  # open 101.5 > 50 planned capital -> floors to 0 shares
    monkeypatch.setattr(book, "_next_open", lambda t, after: (dt.date.today(), 101.5))
    out = book.fill_pending()
    assert out["pending_voided"] == 1
    p = _row(pid)
    assert p["status"] == "void" and p["reason"] == "unfillable-granularity"


def test_stale_pending_voids_after_cutoff(monkeypatch):
    pid = _pending()
    con = book._init()
    try:
        con.execute("UPDATE paper_positions SET created_at=? WHERE id=?",
                    [dt.datetime.now() - dt.timedelta(days=book.PENDING_VOID_AFTER_DAYS + 2), pid])
    finally:
        con.close()
    monkeypatch.setattr(book, "_next_open", lambda t, after: (None, None))
    out = book.fill_pending()
    assert out["pending_voided"] == 1
    assert _row(pid)["reason"] == "no-fill-data"


def _wire_rebalance(monkeypatch, signals):
    monkeypatch.setattr(rebalance, "ROSTER", [{"sid": SID, "kind": "saved", "capital": 100000.0}])
    monkeypatch.setattr(rebalance.store_meta, "get_strategy", lambda sid: {"id": sid, "config": {}})
    monkeypatch.setattr(rebalance, "generate_signals", lambda cfg: {"signals": signals})


def test_rebalance_queues_pending_not_immediate(monkeypatch):
    _wire_rebalance(monkeypatch, [
        {"ticker": "AAA", "action": "buy", "weight": 0.5, "last_close": 100.0},
        {"ticker": "BBB", "action": "buy", "weight": 0.5, "last_close": 200.0},
    ])
    monkeypatch.setattr(book, "_next_open", lambda t, after: (None, None))  # no bar yet
    out = rebalance.rebalance_paper()
    r = out["strategies"][SID]
    assert out["entry_mode"] == "next-open"
    assert r["opened_pending"] == 2 and r["closed"] == 0
    ps = book.list_positions(SID)
    assert len(ps) == 2
    assert all(p["status"] == "pending" and p["entry"] is None for p in ps)


def test_rebalance_leaves_existing_open_positions_untouched(monkeypatch):
    # seed one open position the immediate way at a known price
    monkeypatch.setattr(book, "_latest_close", lambda t: (dt.date.today(), 100.0))
    kept_pid = book.commit_signal(SID, {"ticker": "AAA", "weight": 0.5}, 10000.0)
    before = _row(kept_pid)
    _wire_rebalance(monkeypatch, [{"ticker": "AAA", "action": "hold", "weight": 0.5,
                                   "last_close": 120.0}])
    monkeypatch.setattr(book, "_next_open", lambda t, after: (None, None))
    out = rebalance.rebalance_paper()
    r = out["strategies"][SID]
    assert r["opened_pending"] == 0 and r["closed"] == 0 and r["kept"] == 1
    after = _row(kept_pid)
    assert (after["entry"], after["entry_date"], after["shares"]) == \
        (before["entry"], before["entry_date"], before["shares"])


def test_rebalance_voids_dropped_pending(monkeypatch):
    pid = _pending(ticker="GONE")
    _wire_rebalance(monkeypatch, [])  # empty target: the pending name dropped out pre-fill
    monkeypatch.setattr(book, "_next_open", lambda t, after: (None, None))
    out = rebalance.rebalance_paper()
    assert out["strategies"][SID]["dropped_pending"] == 1
    p = _row(pid)
    assert p["status"] == "void" and p["reason"] == "rebalance-dropped"


def test_scoreboard_counts_pending_without_pnl():
    _pending()
    board = [b for b in book.scoreboard() if b["strategy_id"] == SID]
    assert board and board[0]["pending"] == 1
    assert board[0]["total_pnl"] == 0.0 and board[0]["net_pnl"] == 0.0
