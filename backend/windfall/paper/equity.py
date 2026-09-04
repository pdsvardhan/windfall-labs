"""Per-book daily equity vs benchmark, rebuilt on demand from paper_positions.

No marks history table exists — the book's daily path is reconstructed from each position's
entry/exit and the same adjusted-close panel the marks use, so the curve and the live marks
share one price basis.

The curve is a NAV curve (iter-171, item 1229): equity(day) = (cash + market value of open
positions) / notional - 1, where cash starts at the book's notional and moves by -entry*shares
on an entry and +exit*shares on an exit. That is what the account was actually worth on the day.

It replaces the previous cost-basis ratio, value(day) / sum(every entry ever made), which kept
closed positions in the denominator forever and so counted recycled capital twice. The more a
book rebalanced, the more its return was diluted toward zero: DVM_user reported 7.67% where the
account had in fact made 11.88% gross. Reported drawdowns were measured on that same diluted
series and were wrong for the same reason.

`points` stays GROSS (matching scoreboard.total_pnl, so a book's final point x notional equals
its total_pnl). `points_net` deducts the same modelled NSE delivery costs scoreboard.net_pnl
uses — buy cost paid at entry, sell cost to exit the mark — so the page can show the basis the
project's must_have demands: costs modelled on every entry and exit.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from ..data import trendlyne_store as ts
from ..engine.backtest import DP_FLAT, NSE_BUY_RATE, NSE_SELL_RATE
from .book import list_positions

# The notional every book ran on from inception until the iter-171 step-up. Runs recorded in
# paper_rebalance_runs carry the notional in force for that run, so the curve knows when the base
# changed; anything before the first recorded run was on this.
LEGACY_NOTIONAL = 100000.0


def _notional_steps(sid: str, since: str) -> list[tuple[str, float]]:
    """[(effective_date, notional)] for a book, oldest first, one entry per CHANGE.

    A notional increase is new capital arriving, not a gain. The curve unitizes across it (units are
    issued at the prevailing NAV per unit, exactly as a fund would), so raising a book from Rs1L to
    Rs5L moves the curve by nothing on the day it happens, and the idle cash until the money is
    deployed shows up as the drag it actually is.
    """
    steps: list[tuple[str, float]] = [(since, LEGACY_NOTIONAL)]
    try:
        from ..store_meta import _init
        con = _init()
        try:
            # ran_at is a DATE, so two runs on one day cannot be ordered by it — order by the
            # created_at TIMESTAMP and keep only the LAST run of each day. Without that, a day
            # holding both a Rs5L run and a Rs1L correction (exactly what an aborted notional
            # step-up leaves behind) sorts arbitrarily and injects a phantom step.
            rows = con.execute(
                "SELECT ran_at, notional FROM paper_rebalance_runs WHERE strategy_id=? "
                "AND notional IS NOT NULL ORDER BY ran_at, created_at", [sid]).fetchall()
        finally:
            con.close()
    except Exception:  # noqa: BLE001 — a missing run log must not kill the curves
        rows = []
    last_of_day: dict[str, float] = {}
    for ran_at, notional in rows:
        d = _iso(ran_at)
        if d is not None:
            last_of_day[d] = float(notional)      # later row on the same date wins
    for d in sorted(last_of_day):
        notional = last_of_day[d]
        if notional == steps[-1][1]:
            continue                              # no change — not a step
        if d <= steps[0][0]:
            steps[0] = (steps[0][0], notional)
        else:
            steps.append((d, notional))
    return steps


def _iso(x) -> str | None:
    if x is None:
        return None
    if isinstance(x, (dt.date, dt.datetime)):
        return x.date().isoformat() if isinstance(x, dt.datetime) else x.isoformat()
    return str(x)[:10]


def _with_bhavcopy_fallback(panel, tickers: list[str], start: str):
    """Fill the holes the adjusted panel leaves for held names, from raw Bhavcopy closes.

    Two holes exist. A name the panel does not carry at all gets no column. And a name whose
    Trendlyne history ends earlier than the REST of the batch's gets leading NaNs, because
    adjusted_close_panel splices live Bhavcopy from one batch-wide `last_tl` — the max Trendlyne
    date across every requested symbol — rather than from each symbol's own last bar. SCPL, held in
    DVM_dm_m_20 from 06-Jul, had no value until 09-Jul in a 98-name batch though it prices fine when
    requested alone.

    Either way the position was valued at its ENTRY price for those days: a flat line that jumped to
    the truth only on the exit date (SCPL closed +14.9% with every day in between reported as 0%).
    Valuing a holding at what you paid for it is not a mark.

    Only NaN cells are filled, so adjusted prices always win where they exist. Raw, unadjusted
    prices are acceptable over a paper book's weeks-long window — a corporate action inside it would
    show as a step — but NOT over a backtest's years. The batch-wide `last_tl` itself is left alone
    on purpose: fixing it inside adjusted_close_panel would re-baseline every backtest that has run,
    so it needs an owner decision and an ADR (raised as a finding in iter-171).
    """
    try:
        extra = ts.raw_close_panel(list(tickers), start=start)
    except Exception:  # noqa: BLE001 — a fallback problem must never kill the curves
        return panel
    if extra is None or extra.empty:
        return panel
    idx = panel.index if len(panel.index) else extra.index
    extra = extra.reindex(idx).ffill()
    for col in extra.columns:
        if col not in panel.columns:
            panel[col] = extra[col]
        else:
            panel[col] = panel[col].combine_first(extra[col])
    return panel


def _max_drawdown(navs: list[float]) -> float:
    if not navs:
        return 0.0
    peak, mdd = navs[0], 0.0
    for v in navs:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return mdd


def book_equity(benchmark: str = "NIFTY500") -> dict:
    # Pending next-open entries (iter-147 #248) and voided rows carry no entry price/date yet —
    # they are not part of the book's curve until filled.
    positions = [p for p in list_positions()
                 if p["entry"] is not None and p["status"] in ("open", "closed")]
    by: dict[str, list[dict]] = defaultdict(list)
    for p in positions:
        if p.get("strategy_id"):
            by[p["strategy_id"]].append(p)
    if not by:
        return {"benchmark": benchmark, "books": {}}

    start = min(_iso(p["entry_date"]) for p in positions)
    tickers = sorted({p["ticker"] for p in positions})
    panel = ts.adjusted_close_panel(tickers, start=start, end=None, extend_live=True).ffill()
    panel = _with_bhavcopy_fallback(panel, tickers, start)
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
        steps = _notional_steps(sid, s0)
        unpriced_names: set[str] = set()

        def _state(day: str, i: int, base: float):
            """(nav, nav_net, cash) for this book on `day`, funded by `base` of contributed capital."""
            cash = base
            held = 0.0
            buy_costs = sell_costs = 0.0
            for r in rows:
                if r["entry_date"] > day:
                    continue
                gross_entry = r["entry"] * r["shares"]
                cash -= gross_entry
                buy_costs += gross_entry * NSE_BUY_RATE
                if r["exit_date"] and r["exit_date"] <= day and r["exit"] is not None:
                    proceeds = r["exit"] * r["shares"]
                    cash += proceeds
                    sell_costs += proceeds * NSE_SELL_RATE + DP_FLAT   # realised, sunk
                else:
                    px = panel[r["ticker"]].iloc[i] if r["ticker"] in panel.columns else None
                    if px is None or px != px:
                        # no price for this name on this day — value it at entry (no phantom P&L)
                        # and remember it, so an unpriceable holding is reported, never hidden.
                        unpriced_names.add(r["ticker"])
                        px = r["entry"]
                    mark = float(px) * r["shares"]
                    held += mark
                    sell_costs += mark * NSE_SELL_RATE + DP_FLAT       # cost to exit the mark now
            return cash + held, cash + held - buy_costs - sell_costs, cash

        pts: list[list] = []
        pts_net: list[list] = []
        per_units: list[float] = []
        base = steps[0][1]
        units = base            # NAV per unit starts at 1.0
        step_i = 1
        cash_floor = base
        cash_floor_pct = 1.0

        for i, d in enumerate(dates):
            if d < s0:
                continue
            # Capital moving in or out: issue units on a contribution and redeem them on a
            # withdrawal, both at the prevailing NAV per unit, so the cash flow itself moves the
            # return by nothing (iter-171, item 1236). The redemption half is not optional — with
            # an issue-only guard a notional that goes up and back down leaves the units inflated
            # against an unchanged NAV, which read every book at roughly -79% while all eight were
            # profitable. Same expression serves both directions; only the sign differs.
            while step_i < len(steps) and steps[step_i][0] <= d:
                new_base = steps[step_i][1]
                flow = new_base - base
                if flow != 0 and units > 0:
                    nav_before = _state(d, i, base)[0]
                    if nav_before > 0:
                        units += flow / (nav_before / units)
                base = new_base
                step_i += 1

            nav, nav_net, cash = _state(d, i, base)
            per_units.append(nav / units if units else 0.0)
            cash_floor = min(cash_floor, cash)
            cash_floor_pct = min(cash_floor_pct, cash / base if base else 0.0)
            if units > 0:
                pts.append([d, round(nav / units - 1.0, 6)])
                pts_net.append([d, round(nav_net / units - 1.0, 6)])

        notional = base   # the notional in force today

        b0 = next((bmap[d] for d, _ in pts if d in bmap), None)
        bench_pts = ([[d, round(bmap[d] / b0 - 1, 6)] for d, _ in pts if d in bmap]
                     if b0 else [])
        books[sid] = {
            "start": s0, "points": pts, "points_net": pts_net, "benchmark": bench_pts,
            "notional": notional,
            "notional_steps": [[d, n] for d, n in steps],
            "stats": {
                "gross_return": pts[-1][1] if pts else 0.0,
                "net_return": pts_net[-1][1] if pts_net else 0.0,
                "benchmark_return": bench_pts[-1][1] if bench_pts else None,
                "max_drawdown": round(_max_drawdown(per_units), 6),
                # Cash never deployed. At Rs1L across 20-40 names the per-name slice is smaller
                # than one share of many stocks, so fill_pending's granularity skip leaves capital
                # idle and drags the return — reported, not hidden (iter-171, item 1236).
                "min_cash": round(cash_floor, 2),
                "min_cash_pct": round(cash_floor_pct, 4),
                # A negative floor means the book opened before a close settled (item 1235).
                "cash_went_negative": cash_floor < 0,
                "unpriced_holdings": sorted(unpriced_names),
            },
        }
    return {"benchmark": benchmark, "books": books}
