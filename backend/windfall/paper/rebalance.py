"""Monthly rebalance of the paper book.

For each tracked strategy, regenerate today's target book and sync the open positions to it:
names that dropped out of the top-N are closed (reason='rebalance'); newly-entered names are
queued as PENDING and filled at the next session's open by the daily mark (iter-147, todo #248 —
matches the backtest's next-open fill assumption; adr-038 deferred this to a rebalance boundary).
Names still in the book are kept untouched (so cost basis / hold time are preserved).

Runs on a monthly cron and is also callable via POST /api/paper/rebalance. It rebalances against
whatever data is current — for faithful signals, refresh the Trendlyne pull before running it.
"""
from __future__ import annotations

import datetime as dt

from .. import store_meta
from ..signals_live.generate import generate_blend_signals, generate_signals
from .book import (close_position, commit_pending_signal, list_positions, mark_to_market,
                   void_pending)

# The tracked paper slate (started 2026-07-06). Each runs a Rs1L notional book, sized by signal
# weight. BLEND_70_30 is a synthetic id (no single strategy row) — a fixed 70/30 sleeve blend.
ROSTER = [
    {"sid": "DVM_user", "kind": "saved", "capital": 100000.0},
    {"sid": "DVM_dm_m_20", "kind": "saved", "capital": 100000.0},
    {"sid": "MOM_roc252_m_20", "kind": "saved", "capital": 100000.0},
    {"sid": "CMP_valmom_m_20", "kind": "saved", "capital": 100000.0},
    {"sid": "BLEND_70_30", "kind": "blend", "sleeves": ["MOM_roc252_m_20", "LV_atr_m_20"],
     "weights": [0.7, 0.3], "capital": 100000.0},
]


def _target_book(entry: dict) -> dict:
    """Current target holdings {ticker: signal} — the buy+hold names of today's signal run."""
    if entry["kind"] == "saved":
        strat = store_meta.get_strategy(entry["sid"])
        if not strat:
            return {}
        out = generate_signals(strat["config"])
    else:
        sleeves = []
        for s in entry["sleeves"]:
            st = store_meta.get_strategy(s)
            if not st:
                return {}
            sleeves.append(st["config"])
        out = generate_blend_signals(sleeves, entry["weights"], name=entry["sid"])
    return {s["ticker"]: s for s in out.get("signals", []) if s.get("action") in ("buy", "hold")}


def rebalance_paper() -> dict:
    """Sync every tracked strategy's open positions to its current target book."""
    results = {}
    for entry in ROSTER:
        sid = entry["sid"]
        target = _target_book(entry)
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
        # new entries: in the target but not held or already awaiting fill — queued for the NEXT
        # session's open; the granularity skip (capital < price -> 0 shares) moves to fill time,
        # where the actual fill price is known (book.fill_pending)
        for tk, sig in target.items():
            if tk in held or tk in pending:
                continue
            w = sig.get("weight") or (1.0 / max(len(target), 1))
            cap = entry["capital"] * w
            if cap <= 0:
                continue
            commit_pending_signal(sid, sig, cap)
            opened += 1
        results[sid] = {"target": len(target), "held_before": len(held),
                        "closed": closed, "opened_pending": opened,
                        "dropped_pending": dropped_pending, "kept": len(held) - closed}
    return {"rebalanced_at": str(dt.date.today()), "entry_mode": "next-open",
            "strategies": results, "mark": mark_to_market()}
