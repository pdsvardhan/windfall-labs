"""Per-book daily equity vs benchmark, rebuilt on demand from paper_positions.

No marks history table exists — the book's daily path is reconstructed from each position's
entry/exit and the same adjusted-close panel the marks use, so the curve and the live marks
share one price basis. Returns are GROSS of costs (matching the paper page's stated basis)
and normalized to each book's cost basis: pct(day) = value(day) / cost_basis(day) - 1, where
cost basis only includes positions entered by that day.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from ..data import trendlyne_store as ts
from .book import list_positions


def _iso(x) -> str | None:
    if x is None:
        return None
    if isinstance(x, (dt.date, dt.datetime)):
        return x.date().isoformat() if isinstance(x, dt.datetime) else x.isoformat()
    return str(x)[:10]


def book_equity(benchmark: str = "NIFTY500") -> dict:
    positions = list_positions()
    by: dict[str, list[dict]] = defaultdict(list)
    for p in positions:
        if p.get("strategy_id"):
            by[p["strategy_id"]].append(p)
    if not by:
        return {"benchmark": benchmark, "books": {}}

    start = min(_iso(p["entry_date"]) for p in positions)
    tickers = sorted({p["ticker"] for p in positions})
    panel = ts.adjusted_close_panel(tickers, start=start, end=None, extend_live=True).ffill()
    dates = [d.date().isoformat() for d in panel.index]

    try:
        bser = ts.benchmark_series(benchmark, start=start).ffill()
        bmap = {d.date().isoformat(): float(v) for d, v in bser.items()}
    except Exception:  # noqa: BLE001 — benchmark feed missing shouldn't kill book curves
        bmap = {}

    books: dict[str, dict] = {}
    for sid, ps in by.items():
        rows = []
        for p in ps:
            rows.append({
                "ticker": p["ticker"].upper(), "entry_date": _iso(p["entry_date"]),
                "exit_date": _iso(p.get("exit_date")), "entry": float(p["entry"]),
                "exit": float(p["exit"]) if p.get("exit") is not None else None,
                "shares": float(p["shares"]),
            })
        s0 = min(r["entry_date"] for r in rows)
        pts: list[list] = []
        for i, d in enumerate(dates):
            if d < s0:
                continue
            cost = value = 0.0
            for r in rows:
                if r["entry_date"] > d:
                    continue
                cost += r["entry"] * r["shares"]
                if r["exit_date"] and r["exit_date"] <= d and r["exit"] is not None:
                    value += r["exit"] * r["shares"]
                else:
                    px = panel[r["ticker"]].iloc[i] if r["ticker"] in panel.columns else None
                    value += (float(px) if px == px and px is not None else r["entry"]) * r["shares"]
            if cost > 0:
                pts.append([d, round(value / cost - 1, 6)])
        b0 = next((bmap[d] for d, _ in pts if d in bmap), None)
        bench_pts = ([[d, round(bmap[d] / b0 - 1, 6)] for d, _ in pts if d in bmap]
                     if b0 else [])
        books[sid] = {"start": s0, "points": pts, "benchmark": bench_pts}
    return {"benchmark": benchmark, "books": books}
