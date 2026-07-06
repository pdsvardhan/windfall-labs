"""Paper-trade book backed by the paper_positions table.

Each committed signal becomes a simulated open position. mark_to_market() pulls the latest close
for every open position, updates P&L, and closes positions whose stop or target was hit.
"""
from __future__ import annotations

import datetime as dt
import math

from ..data import trendlyne_store as ts
from ..data.store import connect
from ..store_meta import _init, new_id


def _latest_close(ticker: str):
    # Primary: the Trendlyne survivorship-free store (bare tickers) with the live Bhavcopy splice —
    # the SAME adjusted series the signals/backtests use, so entry and mark stay on one basis. Falls
    # back to the legacy yfinance `prices` table (.NS tickers) for older paper positions.
    try:
        panel = ts.adjusted_close_panel(
            [ticker], start=(dt.date.today() - dt.timedelta(days=40)).isoformat(),
            end=None, extend_live=True)
        col = ticker.upper()
        if col in panel.columns:
            s = panel[col].dropna()
            if len(s):
                return s.index[-1].date(), float(s.iloc[-1])
    except Exception:
        pass
    con = connect(read_only=True)
    try:
        r = con.execute(
            "SELECT date, COALESCE(adj_close, close) AS px FROM prices "
            "WHERE ticker=? AND COALESCE(adj_close, close) IS NOT NULL "
            "ORDER BY date DESC LIMIT 1", [ticker]).fetchone()
    finally:
        con.close()
    if not r:
        return None, None
    return r[0], r[1]


def commit_signal(strategy_id: str | None, signal: dict, capital_per_position: float = 15000.0) -> str:
    entry = signal.get("last_close") or signal.get("entry")
    if not entry or entry <= 0:
        raise ValueError("signal has no usable entry price")
    shares = math.floor(capital_per_position / entry)
    pid = new_id("pp")
    con = _init()
    try:
        con.execute(
            "INSERT INTO paper_positions (id,strategy_id,ticker,status,entry_date,entry,stop,"
            "target,weight,shares,last_price,last_date,return_pct,r_multiple,reason,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [pid, strategy_id, signal["ticker"], "open", dt.date.today(), float(entry),
             signal.get("stop"), signal.get("target"), signal.get("weight", 0.0), float(shares),
             float(entry), dt.date.today(), 0.0, None, None, dt.datetime.now()])
        return pid
    finally:
        con.close()


def mark_to_market() -> dict:
    con = _init()
    try:
        rows = con.execute(
            "SELECT id,ticker,entry,stop,target,shares FROM paper_positions WHERE status='open'"
        ).fetchall()
        updated, closed = 0, 0
        for pid, ticker, entry, stop, target, shares in rows:
            last_date, last_price = _latest_close(ticker)
            if last_price is None:
                continue
            updated += 1
            reason, status, exit_price, exit_date = None, "open", None, None
            if stop is not None and last_price <= stop:
                reason, status, exit_price, exit_date = "stop", "closed", stop, last_date
            elif target is not None and last_price >= target:
                reason, status, exit_price, exit_date = "target", "closed", target, last_date
            mark = exit_price if exit_price is not None else last_price
            ret_pct = (mark / entry - 1.0) if entry else 0.0
            rmult = ((mark - entry) / (entry - stop)) if (stop and entry - stop > 0) else None
            con.execute(
                "UPDATE paper_positions SET last_price=?, last_date=?, return_pct=?, r_multiple=?, "
                "status=?, exit=?, exit_date=?, reason=? WHERE id=?",
                [float(last_price), last_date, float(ret_pct),
                 (float(rmult) if rmult is not None else None), status, exit_price, exit_date,
                 reason, pid])
            if status == "closed":
                closed += 1
        return {"open_marked": updated, "newly_closed": closed}
    finally:
        con.close()


def close_position(pid: str, reason: str = "rebalance") -> bool:
    """Close one open position at the latest EOD close (used by the monthly rebalance for drop-outs)."""
    con = _init()
    try:
        row = con.execute(
            "SELECT ticker, entry, stop FROM paper_positions WHERE id=? AND status='open'", [pid]
        ).fetchone()
        if not row:
            return False
        ticker, entry, stop = row
        last_date, last_price = _latest_close(ticker)
        exit_price = last_price if last_price is not None else entry
        exit_date = last_date if last_date is not None else dt.date.today()
        ret_pct = (exit_price / entry - 1.0) if entry else 0.0
        rmult = ((exit_price - entry) / (entry - stop)) if (stop and entry - stop > 0) else None
        con.execute(
            "UPDATE paper_positions SET status='closed', exit=?, exit_date=?, last_price=?, "
            "last_date=?, return_pct=?, r_multiple=?, reason=? WHERE id=?",
            [float(exit_price), exit_date, float(exit_price), exit_date, float(ret_pct),
             (float(rmult) if rmult is not None else None), reason, pid])
        return True
    finally:
        con.close()


def delete_positions(strategy_id: str) -> int:
    """Hard-delete every position for a strategy_id (e.g. purging a stale test book)."""
    con = _init()
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM paper_positions WHERE strategy_id=?", [strategy_id]).fetchone()[0]
        con.execute("DELETE FROM paper_positions WHERE strategy_id=?", [strategy_id])
        return int(n)
    finally:
        con.close()


def list_positions(strategy_id: str | None = None, status: str | None = None) -> list[dict]:
    con = connect(read_only=True)
    try:
        q = ("SELECT id,strategy_id,ticker,status,entry_date,entry,stop,target,shares,"
             "last_price,last_date,exit,exit_date,return_pct,r_multiple,reason FROM paper_positions WHERE 1=1")
        params: list = []
        if strategy_id:
            q += " AND strategy_id=?"; params.append(strategy_id)
        if status:
            q += " AND status=?"; params.append(status)
        q += " ORDER BY entry_date DESC"
        rows = con.execute(q, params).fetchall()
    finally:
        con.close()
    cols = ["id", "strategy_id", "ticker", "status", "entry_date", "entry", "stop", "target",
            "shares", "last_price", "last_date", "exit", "exit_date", "return_pct", "r_multiple", "reason"]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        for k in ("entry_date", "last_date", "exit_date"):
            d[k] = str(d[k]) if d[k] is not None else None
        out.append(d)
    return out


def scoreboard() -> list[dict]:
    positions = list_positions()
    by_strat: dict[str, list[dict]] = {}
    for p in positions:
        by_strat.setdefault(p["strategy_id"] or "unassigned", []).append(p)
    board = []
    for sid, ps in by_strat.items():
        closed = [p for p in ps if p["status"] == "closed"]
        open_ = [p for p in ps if p["status"] == "open"]
        rets = [p["return_pct"] for p in closed if p["return_pct"] is not None]
        rmults = [p["r_multiple"] for p in closed if p["r_multiple"] is not None]
        pnl = sum(((p["exit"] or p["last_price"] or p["entry"]) - p["entry"]) * (p["shares"] or 0)
                  for p in ps)
        wins = [r for r in rets if r > 0]
        board.append({
            "strategy_id": sid, "open": len(open_), "closed": len(closed),
            "total_pnl": round(pnl, 2),
            "win_rate": round(len(wins) / len(rets), 3) if rets else 0.0,
            "avg_return_pct": round(sum(rets) / len(rets), 4) if rets else 0.0,
            "avg_r_multiple": round(sum(rmults) / len(rmults), 3) if rmults else None,
            "unrealized_open": len(open_),
        })
    return board
