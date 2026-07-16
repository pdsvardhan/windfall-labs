"""Paper-trade book backed by the paper_positions table.

Each committed signal becomes a simulated open position. mark_to_market() pulls the latest close
for every open position, updates P&L, and closes positions whose stop or target was hit.
"""
from __future__ import annotations

import datetime as dt
import logging
import math

from ..data import trendlyne_store as ts
from ..data.store import connect
from ..engine.backtest import DP_FLAT, NSE_BUY_RATE, NSE_SELL_RATE
from ..store_meta import _init, new_id

_log = logging.getLogger(__name__)


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
    except Exception as exc:  # noqa: BLE001
        # Don't hide data errors behind a bare pass (audit #184): log and fall through to the legacy
        # prices table, so a Trendlyne-store failure is visible instead of silently zero-marking.
        _log.warning("paper mark: trendlyne price lookup failed for %s: %r", ticker, exc)
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
    # Enter at the latest EXECUTABLE close — what you'd actually pay committing the trade now — not the
    # signal bar's close. When signals resolve on stale data (as-of an older bar than today), pricing
    # entry at that older close and then marking to the current close books phantom day-0 P&L for the
    # gap the account never held (audit 2026-07-06). Fall back to the signal's own close if the store
    # has no fresh price. entry_date is set to the price's date so entry and first mark share one bar.
    entry_date, latest = _latest_close(signal["ticker"])
    entry = latest if (latest and latest > 0) else (signal.get("last_close") or signal.get("entry"))
    if not entry or entry <= 0:
        raise ValueError("signal has no usable entry price")
    entry_date = entry_date or dt.date.today()
    shares = math.floor(capital_per_position / entry)
    pid = new_id("pp")
    con = _init()
    try:
        con.execute(
            "INSERT INTO paper_positions (id,strategy_id,ticker,status,entry_date,entry,stop,"
            "target,weight,shares,last_price,last_date,return_pct,r_multiple,reason,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [pid, strategy_id, signal["ticker"], "open", entry_date, float(entry),
             signal.get("stop"), signal.get("target"), signal.get("weight", 0.0), float(shares),
             float(entry), entry_date, 0.0, None, None, dt.datetime.now()])
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
    # Per-name mark-staleness flag (audit #184): the mark cron prices every open name to the latest bar
    # it can find; a name the store could not refresh lags the freshest mark. Flag any open position whose
    # last_date is behind the newest last_date among open positions, so a stale mark can't masquerade as
    # a live one. (ISO date strings compare lexically.)
    open_dates = [d["last_date"] for d in out if d["status"] == "open" and d["last_date"]]
    ref = max(open_dates) if open_dates else None
    for d in out:
        d["stale_mark"] = bool(ref and d["status"] == "open" and d["last_date"] and d["last_date"] < ref)
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
        # Net P&L after the modelled NSE delivery costs (same side-aware rates + flat DP the backtest
        # deducts, adr-020): buy cost is already spent, sell cost is what you'd pay to exit the mark now.
        # So paper P&L is reported net-of-costs, not just gross (audit #184).
        net_pnl = sum(_net_pnl(p) for p in ps)
        wins = [r for r in rets if r > 0]
        board.append({
            "strategy_id": sid, "open": len(open_), "closed": len(closed),
            "total_pnl": round(pnl, 2), "net_pnl": round(net_pnl, 2),
            "win_rate": round(len(wins) / len(rets), 3) if rets else 0.0,
            "avg_return_pct": round(sum(rets) / len(rets), 4) if rets else 0.0,
            "avg_r_multiple": round(sum(rmults) / len(rmults), 3) if rmults else None,
            "unrealized_open": len(open_),
        })
    return board


def _net_pnl(p: dict) -> float:
    """Position P&L net of modelled NSE delivery costs (round-trip: buy paid at entry, sell to exit the
    current mark). Mirrors engine.backtest's cost model so paper and backtest report on one basis."""
    entry = p["entry"] or 0.0
    shares = p["shares"] or 0.0
    mark = p["exit"] or p["last_price"] or entry
    if entry <= 0 or shares <= 0:
        return 0.0
    gross = (mark - entry) * shares
    buy_cost = shares * entry * NSE_BUY_RATE
    sell_cost = shares * mark * NSE_SELL_RATE + DP_FLAT
    return gross - buy_cost - sell_cost
