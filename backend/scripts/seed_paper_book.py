"""Seed a paper book for a stored strategy: run today's signals, commit every BUY.

Usage: python3 seed_paper_book.py <strategy_id> [notional=100000]

Refuses to seed a strategy that already has open paper positions (no double books).
Entry prices come from commit_signal's latest-executable-close rule — same as every
other live book. Used 2026-07-17 to start the survivor cohort (iteration 94 item 657).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

API = os.environ.get("WINDFALL_API", "http://127.0.0.1:8505")


def call(path: str, body: dict | None = None, timeout: float = 600.0):
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"}, method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: seed_paper_book.py <strategy_id> [notional]")
    sid = sys.argv[1]
    notional = float(sys.argv[2]) if len(sys.argv) > 2 else 100000.0

    existing = call(f"/api/paper/positions?strategy_id={sid}&status=open")
    if existing:
        sys.exit(f"refusing: {sid} already has {len(existing)} open paper positions")

    cfg = call(f"/api/strategies/{sid}")["config"]
    run = call("/api/signals", {"config": cfg, "strategy_id": sid, "save": True})
    # A fresh book takes the strategy's whole target book: "buy" (new vs the previous saved
    # signal run) AND "hold" (carried names). Only "sell" rows are outside today's book.
    buys = [s for s in run.get("signals", []) if s.get("action") in ("buy", "hold")]
    if not buys:
        sys.exit(f"no buy/hold signals for {sid} (as_of {run.get('as_of')})")

    per_position = notional / len(buys)
    committed = []
    for s in buys:
        out = call("/api/paper/commit", {"strategy_id": sid, "signal": s,
                                         "capital_per_position": per_position})
        committed.append((s["ticker"], out.get("position_id")))
    print(f"{sid}: committed {len(committed)} positions "
          f"(as_of {run.get('as_of')}, ~{per_position:.0f}/position, "
          f"signal_run {run.get('signal_run_id')})")
    for tk, pid in committed:
        print(f"  {tk} -> {pid}")


if __name__ == "__main__":
    main()
