"""Monthly rebalance of the paper book.

For each tracked strategy, regenerate today's target book and sync the open positions to it:
names that dropped out of the top-N are closed (reason='rebalance'); newly-entered names are opened.
Names still in the book are kept untouched (so cost basis / hold time are preserved).

Runs on a monthly cron and is also callable via POST /api/paper/rebalance. It rebalances against
whatever data is current — for faithful signals, refresh the Trendlyne pull before running it.
"""
from __future__ import annotations

import datetime as dt

from .. import store_meta
from ..signals_live.generate import generate_blend_signals, generate_signals
from .book import close_position, commit_signal, list_positions, mark_to_market

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
        closed = opened = 0
        # drop-outs: held but no longer in the target
        for tk, p in held.items():
            if tk not in target and close_position(p["id"], reason="rebalance"):
                closed += 1
        # new entries: in the target but not currently held
        for tk, sig in target.items():
            if tk in held:
                continue
            w = sig.get("weight") or (1.0 / max(len(target), 1))
            cap = entry["capital"] * w
            px = sig.get("last_close") or 0
            if px <= 0 or cap < px:  # would floor to 0 shares — skip (small-account granularity)
                continue
            commit_signal(sid, sig, cap)
            opened += 1
        results[sid] = {"target": len(target), "held_before": len(held),
                        "closed": closed, "opened": opened, "kept": len(held) - closed}
    return {"rebalanced_at": str(dt.date.today()), "strategies": results, "mark": mark_to_market()}
