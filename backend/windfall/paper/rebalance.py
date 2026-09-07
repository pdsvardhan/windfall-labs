"""Rebalance of the paper books.

For each tracked strategy that is DUE, regenerate today's target book and sync the open positions
to it: names that dropped out of the top-N are closed (reason='rebalance'); newly-entered names are
queued as PENDING and filled at the next session's open by the daily mark (iter-147, todo #248 —
matches the backtest's next-open fill assumption; adr-038 deferred this to a rebalance boundary).
Names still in the book are kept untouched (so cost basis / hold time are preserved).

Cadence (iter-171, item 1231): each book rebalances on its own config cadence — weekly, monthly or
quarterly — decided here rather than by which cron fired. Previously the only cron was monthly on
the 1st, so DVM_all_w_10 (a weekly strategy) could not have been rebalanced correctly even if it had
been on the roster. The cron now runs daily and this function decides who is due, comparing the
current period against each book's last recorded run: a run missed to a holiday or a failure is
caught up on the next day rather than skipped for the whole period, and a second run inside the same
period is a no-op.

Callable via POST /api/paper/rebalance. It rebalances against whatever data is current — for
faithful signals, refresh the Trendlyne pull before running it.
"""
from __future__ import annotations

import datetime as dt

from .. import store_meta
from ..signals_live.generate import generate_blend_signals, generate_signals
from ..store_meta import _init, new_id
from ..engine.backtest import DP_FLAT, NSE_BUY_RATE, NSE_SELL_RATE
from .book import (close_position, commit_pending_signal, list_positions, mark_to_market,
                   void_pending)

# Notional per paper book.
#
# The owner's decision (iter-171, item 1236) is to run these books at Rs5L, matching the real account
# size the strategies are designed for: at Rs1L a 20-40 name book allocates Rs2.5-5K per name, less
# than one share of many NSE stocks, so fill_pending's granularity rule voided those entries and left
# idle cash the backtests never assume — they invest_fully. The drag was WORST on the widest books
# (min-cash Rs25,758 of Rs1L, 25.8%, on the 40-name BLEND_70_30; 28 unfillable-granularity voids, 24
# of them BLEND at Rs1,500-3,500 slices). It was NOT uniform: measured min-cash across the eight was
# 1.26% (DVM_user) to 25.8% (BLEND), and CMP_valmom_m_20 ran slightly NEGATIVE at -0.86%. Earlier
# notes in this file said "11-26% of every book"; that overstated four of the eight.
#
# FLIPPED 2026-09-08 (iter-173, to-do #819). The flip had a required ORDER, because raising the
# notional alone does not resize existing holdings — a book would keep its Rs1L of positions and
# carry Rs4L of idle cash (measured 2026-09-04: DVM_user came out 80% cash), a worse distortion than
# the drag being fixed. Each precondition was checked before this line changed:
#   1. Trendlyne refresh landed (iter-172) — prices, valuation_ratios and fundamentals all current.
#   2. adr-046 restored the selectable universe from 293 to 1,946 names. This mattered: every
#      persisted signal run was generated 2026-09-07 07:23-07:26 IST, ~11h BEFORE adr-046 landed at
#      18:35, so resizing against those runs would have re-entered all eight books into baskets
#      chosen from 14% of the market.
#   3. A fresh signal run per book returned as_of 2026-09-07, data_age_days 0, no stale warnings.
#   4. resize_book() flattened each book, then a forced rebalance re-entered it at the new size.
#
# Resizing re-bases a live track record and costs a full round-trip of modelled brokerage/STT, so it
# stays a deliberate operator action (resize_book is never a side effect of this constant).
BOOK_NOTIONAL = 500000.0

# The tracked paper slate (started 2026-07-06). BLEND_70_30 is a synthetic id (no single strategy
# row) — a fixed 70/30 sleeve blend.
#
# MOM_roc252_m_10, DVM_all_w_10 and DVM_all_m_10 joined on 2026-09-04 (iter-171, item 1230). They
# had positions seeded 2026-06-29 but were never on the roster, so they sat as buy-and-hold baskets
# through the 1-Aug and 1-Sep rebalances while still being marked daily and published on the
# scoreboard as if they were live books — which is also why the weekly and monthly DVM_all_10
# variants reported byte-identical returns. They are the three the 2026-07-17 robustness protocol
# rated 'survivor', the only three that passed it. Their existing baskets are kept, so the track
# record since June continues rather than restarting.
ROSTER = [
    {"sid": "DVM_user", "kind": "saved", "capital": BOOK_NOTIONAL},
    {"sid": "DVM_dm_m_20", "kind": "saved", "capital": BOOK_NOTIONAL},
    {"sid": "MOM_roc252_m_20", "kind": "saved", "capital": BOOK_NOTIONAL},
    {"sid": "CMP_valmom_m_20", "kind": "saved", "capital": BOOK_NOTIONAL},
    {"sid": "MOM_roc252_m_10", "kind": "saved", "capital": BOOK_NOTIONAL},
    {"sid": "DVM_all_w_10", "kind": "saved", "capital": BOOK_NOTIONAL},
    {"sid": "DVM_all_m_10", "kind": "saved", "capital": BOOK_NOTIONAL},
    {"sid": "BLEND_70_30", "kind": "blend", "sleeves": ["MOM_roc252_m_20", "LV_atr_m_20"],
     "weights": [0.7, 0.3], "capital": BOOK_NOTIONAL},
]

DEFAULT_CADENCE = "monthly"


def _cadence(entry: dict) -> str:
    """The book's rebalance cadence, from its saved strategy config."""
    if entry["kind"] == "saved":
        strat = store_meta.get_strategy(entry["sid"])
        if strat:
            return (strat["config"].get("rebalance") or DEFAULT_CADENCE).lower()
        return DEFAULT_CADENCE
    # A blend rebalances as often as its most frequent sleeve.
    order = {"weekly": 0, "monthly": 1, "quarterly": 2}
    cads = []
    for s in entry.get("sleeves", []):
        st = store_meta.get_strategy(s)
        if st:
            cads.append((st["config"].get("rebalance") or DEFAULT_CADENCE).lower())
    return min(cads, key=lambda c: order.get(c, 1)) if cads else DEFAULT_CADENCE


def _period_key(day: dt.date, cadence: str):
    """The rebalance period `day` falls in. Two runs sharing a key are the same rebalance."""
    if cadence == "weekly":
        iso = day.isocalendar()
        return ("W", iso[0], iso[1])
    if cadence == "quarterly":
        return ("Q", day.year, (day.month - 1) // 3)
    if cadence == "daily":
        return ("D", day.toordinal())
    return ("M", day.year, day.month)


def _last_run(sid: str) -> dt.date | None:
    con = _init()
    try:
        r = con.execute(
            "SELECT MAX(ran_at) FROM paper_rebalance_runs WHERE strategy_id=?", [sid]).fetchone()
        return r[0] if r and r[0] else None
    finally:
        con.close()


def _record_run(sid: str, ran_at: dt.date, cadence: str, notional: float,
                target_n: int, closed: int, opened: int) -> None:
    con = _init()
    try:
        con.execute(
            "INSERT INTO paper_rebalance_runs "
            "(id,strategy_id,ran_at,cadence,notional,target_n,closed,opened,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [new_id("prr"), sid, ran_at, cadence, float(notional), int(target_n),
             int(closed), int(opened), dt.datetime.now()])
    finally:
        con.close()


def is_due(entry: dict, today: dt.date) -> tuple[bool, str]:
    """Is this book due to rebalance today? Returns (due, cadence)."""
    cadence = _cadence(entry)
    last = _last_run(entry["sid"])
    if last is None:
        return True, cadence          # never recorded a run — rebalance now and start the clock
    if isinstance(last, dt.datetime):
        last = last.date()
    return _period_key(today, cadence) != _period_key(last, cadence), cadence


# A signal run that trips one of these is not a fresh book — it is the last book the data could
# still produce, re-derived (iter-171, item 1233). The engine has always said so in `warnings`; the
# cron logged 400 characters of the response and nothing read them, so the 1-Aug and 1-Sep runs both
# rebalanced on a 22-July book with no alert for six weeks. Now the run reports its own health and
# the cron alerts on it.
STALE_WARNING_MARKERS = (
    "no eligible universe",
    "stale point-in-time",
    "refresh data before trading",
)
DATA_AGE_ALERT_DAYS = 35   # same threshold the fundamentals snapshot calls stale


def _target_book(entry: dict) -> tuple[dict, dict]:
    """(target holdings, signal-run health) — the buy+hold names of today's signal run."""
    if entry["kind"] == "saved":
        strat = store_meta.get_strategy(entry["sid"])
        if not strat:
            return {}, {"error": f"no saved strategy {entry['sid']}"}
        out = generate_signals(strat["config"])
    else:
        sleeves = []
        for s in entry["sleeves"]:
            st = store_meta.get_strategy(s)
            if not st:
                return {}, {"error": f"no saved sleeve {s}"}
            sleeves.append(st["config"])
        out = generate_blend_signals(sleeves, entry["weights"], name=entry["sid"])
    warnings = out.get("warnings") or []
    age = out.get("data_age_days")
    stale = [w for w in warnings
             if any(m in str(w).lower() for m in STALE_WARNING_MARKERS)]
    health = {
        "as_of": out.get("as_of"),
        "data_age_days": age,
        "stale_warnings": stale,
        "is_stale": bool(stale) or (age is not None and age > DATA_AGE_ALERT_DAYS),
    }
    return ({s["ticker"]: s for s in out.get("signals", [])
             if s.get("action") in ("buy", "hold")}, health)


def available_cash(sid: str, notional: float) -> float:
    """What the book can actually spend right now, net of modelled costs.

    Cash, not notional-minus-open-cost: every entry ever made leaves the account and every exit
    returns its proceeds, so realized P&L belongs in the balance. Sizing off open cost alone
    ignores realized LOSSES and overstates capacity by exactly the amount lost — measured at up to
    Rs6,279 on MOM_roc252_m_10 — which is how a book overdrew in the first place (item 1235).
    Pending entries are money already committed to a fill, so they are held back too.

    NET OF MODELLED COSTS since 2026-09-08 (to-do #864). It used to net none of them: entry and
    exit are raw prices, so the balance carried GROSS realized P&L and never paid the brokerage/STT
    the scoreboard deducts. DVM_user read Rs12,190.20 against net_pnl Rs11,578.46 — Rs611.74 of
    cash the book would never actually have, Rs5,321.05 across the eight books, and it scaled 5x
    with the Rs5L flip.

    Only costs that have ACTUALLY been paid are deducted, which is where this differs from
    book._net_pnl: that function marks a position to market and therefore models the exit cost of a
    sale that has not happened. A cash balance must not. So an open position pays only its buy
    cost, and the sell cost appears when the position closes.
    """
    cash = notional
    for p in list_positions(sid):
        if p["status"] in ("open", "closed") and p["entry"] and p["shares"]:
            gross = p["entry"] * p["shares"]
            cash -= gross + gross * NSE_BUY_RATE          # the buy, and what it cost to place it
        if p["status"] == "closed" and p["exit"] and p["shares"]:
            proceeds = p["exit"] * p["shares"]
            cash += proceeds - (proceeds * NSE_SELL_RATE + DP_FLAT)
        if p["status"] == "pending":
            cash -= p.get("planned_capital") or 0.0
    return cash


def rebalance_paper(today: dt.date | None = None, force: bool = False) -> dict:
    """Sync every DUE tracked strategy's open positions to its current target book."""
    today = today or dt.date.today()
    results = {}
    health_by_book = {}
    for entry in ROSTER:
        sid = entry["sid"]
        due, cadence = is_due(entry, today)
        if not (due or force):
            results[sid] = {"skipped": "not-due", "cadence": cadence}
            continue

        target, health = _target_book(entry)
        health_by_book[sid] = health
        held = {p["ticker"]: p for p in list_positions(sid, status="open")}
        pending = {p["ticker"]: p for p in list_positions(sid, status="pending")}
        closed = opened = dropped_pending = 0
        # drop-outs: held but no longer in the target
        for tk, p in held.items():
            if tk not in target and close_position(p["id"], reason="rebalance"):
                closed += 1
        # a never-filled pending entry whose name dropped out is voided, not closed (no P&L existed)
        for tk, p in pending.items():
            if tk not in target and void_pending(p["id"]):
                dropped_pending += 1

        # New entries are funded from what the book actually has left, re-read AFTER this run's
        # closes (iter-171, item 1235). Sizing purely off the notional let a rebalance commit more
        # than the book held — CMP_valmom_m_20's reconstructed cash floor hit -Rs861.51, so the book
        # briefly traded on capital it did not have and its return was computed on an inflated base.
        notional = float(entry["capital"])
        available = available_cash(sid, notional)
        underfunded = 0
        for tk, sig in target.items():
            if tk in held or tk in pending:
                continue
            w = sig.get("weight") or (1.0 / max(len(target), 1))
            cap = notional * w
            if cap <= 0:
                continue
            if cap > available:
                # Not enough cash left for a full-size slice. Take what is left if it is a
                # meaningful slice, otherwise skip the name and say so — never overdraw.
                if available < cap * 0.5:
                    underfunded += 1
                    continue
                cap = available
            commit_pending_signal(sid, sig, cap)
            available -= cap
            opened += 1

        _record_run(sid, today, cadence, notional, len(target), closed, opened)
        results[sid] = {"target": len(target), "held_before": len(held),
                        "closed": closed, "opened_pending": opened,
                        "dropped_pending": dropped_pending, "kept": len(held) - closed,
                        "cadence": cadence, "notional": notional,
                        "cash_left": round(available, 2),
                        "underfunded_skips": underfunded,
                        "signal_health": health_by_book.get(sid)}

    # When nothing was due, no signal run happened — say so rather than reporting an all-clear
    # nobody checked. A reassuring "signals current" asserted on zero evidence is the same failure
    # mode item 1233 exists to remove.
    if not health_by_book:
        return {"rebalanced_at": str(today), "entry_mode": "next-open", "strategies": results,
                "data_health": {"stale": None, "stale_books": [], "worst_data_age_days": None,
                                "signal_as_of": [],
                                "message": "not evaluated - no book was due, so no signals ran"},
                "mark": mark_to_market()}

    stale_books = sorted(sid for sid, h in health_by_book.items() if h.get("is_stale"))
    ages = [h["data_age_days"] for h in health_by_book.values()
            if h.get("data_age_days") is not None]
    as_ofs = sorted({str(h["as_of"]) for h in health_by_book.values() if h.get("as_of")})
    data_health = {
        "stale": bool(stale_books),
        "stale_books": stale_books,
        "worst_data_age_days": max(ages) if ages else None,
        "signal_as_of": as_ofs,
        "message": (
            f"signals are STALE for {len(stale_books)} of {len(health_by_book)} book(s) "
            f"(as_of {', '.join(as_ofs) or 'unknown'}, data age "
            f"{max(ages) if ages else '?'}d) — this rebalance re-derived an old book rather "
            f"than a current one; refresh the Trendlyne pull"
            if stale_books else "signals current"),
    }
    return {"rebalanced_at": str(today), "entry_mode": "next-open",
            "strategies": results, "data_health": data_health,
            "mark": mark_to_market()}


def void_pending_entries(sid: str) -> dict:
    """Void every not-yet-filled entry for a book, leaving open positions untouched.

    An operational undo for a rebalance queued under the wrong parameters — a pending row carries no
    price and no P&L until the next open fills it, so voiding one before that costs nothing. Added
    iter-171 after a rebalance run under a Rs5L notional queued 34 entries at the wrong slice size.
    """
    voided = 0
    for p in list_positions(sid, status="pending"):
        if void_pending(p["id"], reason="voided-by-operator"):
            voided += 1
    return {"strategy_id": sid, "voided_pending": voided}


def resize_book(sid: str, notional: float | None = None) -> dict:
    """Re-baseline ONE book to the current notional: close every open position and let the next
    rebalance re-enter the target at the new slice size.

    Deliberately manual (iter-171, item 1236). Raising the book notional does not re-size existing
    holdings on its own, because doing so costs a full round-trip of modelled brokerage/STT and
    re-bases a live track record — that is the owner's call, not a side effect of a config change.
    """
    entry = next((e for e in ROSTER if e["sid"] == sid), None)
    if entry is None:
        raise ValueError(f"{sid} is not a tracked book")
    target_notional = float(notional if notional is not None else entry["capital"])
    closed = 0
    for p in list_positions(sid, status="open"):
        if close_position(p["id"], reason="resize"):
            closed += 1
    voided = 0
    for p in list_positions(sid, status="pending"):
        if void_pending(p["id"], reason="resize"):
            voided += 1
    return {"strategy_id": sid, "closed": closed, "voided_pending": voided,
            "notional": target_notional,
            "note": "book flat — the next rebalance re-enters the target at the new slice size"}
