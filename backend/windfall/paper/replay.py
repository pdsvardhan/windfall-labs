"""Replay the paper books from a past start date, exactly as the live paper process would have run.

Owner decision 2026-10-19 (iteration 197, adr-048): all eight books should carry one continuous
record from the end of June on Rs5L. Before this, the three 5y-study survivors sat as frozen
buy-and-hold baskets from 29 Jun to 4 Sep, the other five started on 6 Jul, and every book ran on
Rs1L until the 7-Sep resize — three different histories under one headline.

This is NOT a backtest. It re-runs the paper process itself, day by day, through the same rules the
two crons apply to the live books:

  20:40 Mon-Fri  (windfall-paper-mark)       fill_pending, then mark_to_market
  21:30 daily    (windfall-paper-rebalance)  rebalance_paper for every book that is due

  - selection: generate_signals / generate_blend_signals AS OF the rebalance day — the same code,
    reading only the point-in-time panels up to that bar;
  - cadence: a book is due on the first calendar day of a new period (rebalance._period_key) — so a
    monthly book started 29 Jun rebalances again on 1 Jul, and a month starting on a Saturday is
    rebalanced on that Saturday off Friday's close, exactly as the daily cron did;
  - exits: drop-outs close at the rebalance day's close; stop/target are checked against each
    weekday's close and exit AT the stop/target level (book.mark_to_market's rule);
  - entries: queued as pending, filled at the first open strictly after the commit day with
    floor(planned_capital / open) shares, voided below one share or after 14 days without a bar;
  - sizing: notional x signal weight, capped by available_cash — net of the costs actually paid.

The simulation core (`simulate_book`) is pure: prices, targets and calendar in, rows out. Only
`replay_paper` touches the data layer and the database, and it writes nothing unless apply=True.
Replayed rows are stored with origin='replay'; the UI does not distinguish them (owner's choice).
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

import pandas as pd

from ..engine.backtest import DP_FLAT, NSE_BUY_RATE, NSE_SELL_RATE
from .book import PENDING_VOID_AFTER_DAYS
from .rebalance import _period_key

REPLAY_START = dt.date(2026, 6, 29)
_LOOKBACK_DAYS = 40   # book._latest_close reads a 40-day window; a mark never reaches further back


@dataclass
class _Pos:
    ticker: str
    status: str                      # pending | open | closed | void
    created_at: dt.datetime
    planned_capital: float
    weight: float
    stop: float | None
    target: float | None
    entry_date: dt.date | None = None
    entry: float | None = None
    shares: float | None = None
    last_price: float | None = None
    last_date: dt.date | None = None
    exit: float | None = None
    exit_date: dt.date | None = None
    return_pct: float | None = None
    r_multiple: float | None = None
    reason: str | None = None


@dataclass
class _Book:
    sid: str
    notional: float
    cadence: str
    positions: list[_Pos] = field(default_factory=list)
    runs: list[dict] = field(default_factory=list)
    last_run: dt.date | None = None


def _bar_on_or_before(series: pd.Series, day: dt.date, lookback: int = _LOOKBACK_DAYS):
    """(date, price) of the latest non-NaN bar at or before `day`, within the mark's lookback."""
    s = series.loc[:pd.Timestamp(day)].dropna()
    if not len(s):
        return None, None
    d = s.index[-1].date()
    if (day - d).days > lookback:
        return None, None
    return d, float(s.iloc[-1])


def _first_bar_after(series: pd.Series, after: dt.date, until: dt.date):
    """(date, price) of the first non-NaN bar strictly after `after` and on/before `until`."""
    s = series.loc[pd.Timestamp(after) + pd.Timedelta(days=1):pd.Timestamp(until)].dropna()
    if not len(s):
        return None, None
    return s.index[0].date(), float(s.iloc[0])


def _rmult(price: float, entry: float, stop: float | None):
    return ((price - entry) / (entry - stop)) if (stop and entry - stop > 0) else None


def _available_cash(b: _Book) -> float:
    """rebalance.available_cash over the in-memory book: net of costs actually paid."""
    cash = b.notional
    for p in b.positions:
        if p.status in ("open", "closed") and p.entry and p.shares:
            gross = p.entry * p.shares
            cash -= gross + gross * NSE_BUY_RATE
        if p.status == "closed" and p.exit and p.shares:
            proceeds = p.exit * p.shares
            cash += proceeds - (proceeds * NSE_SELL_RATE + DP_FLAT)
        if p.status == "pending":
            cash -= p.planned_capital or 0.0
    return cash


def _fill_pending(b: _Book, day: dt.date, opens: pd.DataFrame) -> None:
    """book.fill_pending as run by the mark cron on `day`."""
    for p in b.positions:
        if p.status != "pending":
            continue
        committed = p.created_at.date()
        col = opens[p.ticker] if p.ticker in opens.columns else None
        fill_date, px = (_first_bar_after(col, committed, day) if col is not None else (None, None))
        if px is None or px <= 0:
            if (day - committed).days > PENDING_VOID_AFTER_DAYS:
                p.status, p.reason = "void", "no-fill-data"
            continue
        shares = math.floor((p.planned_capital or 0) / px)
        if shares < 1:
            p.status, p.reason = "void", "unfillable-granularity"
            continue
        p.status, p.entry, p.entry_date, p.shares = "open", px, fill_date, float(shares)
        p.last_price, p.last_date, p.return_pct = px, fill_date, 0.0


def _mark(b: _Book, day: dt.date, closes: pd.DataFrame) -> None:
    """book.mark_to_market's price + stop/target pass on `day` (exit AT the stop/target level)."""
    for p in b.positions:
        if p.status != "open":
            continue
        if p.ticker not in closes.columns:
            continue
        last_date, last_price = _bar_on_or_before(closes[p.ticker], day)
        if last_price is None:
            continue                                   # unpriced: left unmarked, as live does
        status, reason, exit_price, exit_date = "open", None, None, None
        if p.stop is not None and last_price <= p.stop:
            status, reason, exit_price, exit_date = "closed", "stop", p.stop, last_date
        elif p.target is not None and last_price >= p.target:
            status, reason, exit_price, exit_date = "closed", "target", p.target, last_date
        mark = exit_price if exit_price is not None else last_price
        p.last_price, p.last_date = last_price, last_date
        p.return_pct = (mark / p.entry - 1.0) if p.entry else 0.0
        p.r_multiple = _rmult(mark, p.entry, p.stop)
        if status == "closed":
            p.status, p.reason, p.exit, p.exit_date = "closed", reason, exit_price, exit_date


def _close(p: _Pos, day: dt.date, closes: pd.DataFrame, reason: str) -> None:
    """book.close_position: exit at the latest close (entry if there is none)."""
    d, px = (_bar_on_or_before(closes[p.ticker], day) if p.ticker in closes.columns
             else (None, None))
    exit_price = px if px is not None else p.entry
    exit_date = d if d is not None else day
    p.status, p.exit, p.exit_date, p.reason = "closed", exit_price, exit_date, reason
    p.last_price, p.last_date = exit_price, exit_date
    p.return_pct = (exit_price / p.entry - 1.0) if p.entry else 0.0
    p.r_multiple = _rmult(exit_price, p.entry, p.stop)


def _rebalance(b: _Book, day: dt.date, target: dict[str, dict], closes: pd.DataFrame) -> None:
    """rebalance.rebalance_paper for one due book on `day`."""
    held = {p.ticker: p for p in b.positions if p.status == "open"}
    pending = {p.ticker: p for p in b.positions if p.status == "pending"}
    closed = opened = 0
    for tk, p in held.items():
        if tk not in target:
            _close(p, day, closes, "rebalance")
            closed += 1
    for tk, p in pending.items():
        if tk not in target:
            p.status, p.reason = "void", "rebalance-dropped"
    available = _available_cash(b)
    commit_at = dt.datetime.combine(day, dt.time(21, 30))
    for tk, sig in target.items():
        if tk in held or tk in pending:
            continue
        w = sig.get("weight") or (1.0 / max(len(target), 1))
        cap = b.notional * w
        if cap <= 0:
            continue
        if cap > available:
            if available < cap * 0.5:
                continue
            cap = available
        b.positions.append(_Pos(ticker=tk, status="pending", created_at=commit_at,
                                planned_capital=float(cap), weight=sig.get("weight", 0.0),
                                stop=sig.get("stop"), target=sig.get("target")))
        available -= cap
        opened += 1
    b.runs.append({"ran_at": day, "cadence": b.cadence, "notional": b.notional,
                   "target_n": len(target), "closed": closed, "opened": opened,
                   "created_at": commit_at})
    b.last_run = day


def rebalance_days(cadence: str, start: dt.date, end: dt.date) -> list[dt.date]:
    """Every day the daily rebalance cron would have found this book due, from a first run on start."""
    days, last = [], None
    d = start
    while d <= end:
        if last is None or _period_key(d, cadence) != _period_key(last, cadence):
            days.append(d)
            last = d
        d += dt.timedelta(days=1)
    return days


def simulate_book(sid: str, notional: float, cadence: str, targets: dict[dt.date, dict],
                  opens: pd.DataFrame, closes: pd.DataFrame,
                  start: dt.date, end: dt.date) -> _Book:
    """Run the two paper crons over [start, end] for one book. Pure — no I/O."""
    b = _Book(sid=sid, notional=float(notional), cadence=cadence)
    d = start
    while d <= end:
        if d.weekday() < 5:                     # 20:40 mark cron, weekdays
            _fill_pending(b, d, opens)
            _mark(b, d, closes)
        if d in targets:                        # 21:30 rebalance cron, when due
            _rebalance(b, d, targets[d], closes)
            _fill_pending(b, d, opens)          # rebalance_paper ends with mark_to_market,
            _mark(b, d, closes)                 # which fills first and then marks
        d += dt.timedelta(days=1)
    return b


# ── data-layer driver ────────────────────────────────────────────────────────

def _targets_for(entry: dict, days: list[dt.date]) -> tuple[dict[dt.date, dict], list[str]]:
    """{day: {ticker: signal}} for one roster entry — the buy+hold names, in signal order."""
    from .. import store_meta
    from ..signals_live.generate import (generate_blend_signals, generate_signals,
                                         resolve_live)

    problems: list[str] = []
    out: dict[dt.date, dict] = {}
    if entry["kind"] == "saved":
        cfg = store_meta.get_strategy(entry["sid"])["config"]
        rs = resolve_live(cfg)
        runs = {d: generate_signals(cfg, as_of=d, rs=rs) for d in days}
    else:
        cfgs = [store_meta.get_strategy(s)["config"] for s in entry["sleeves"]]
        rss = [resolve_live(c) for c in cfgs]
        runs = {d: generate_blend_signals(cfgs, entry["weights"], name=entry["sid"], as_of=d,
                                          rs_list=rss) for d in days}
    for d, run in runs.items():
        tgt = {s["ticker"]: s for s in run.get("signals", []) if s.get("action") in ("buy", "hold")}
        if not tgt:
            problems.append(f"{entry['sid']} {d}: empty target ({'; '.join(run.get('warnings', []))[:200]})")
        stale = [w for w in run.get("warnings", []) if "no eligible universe" in str(w).lower()
                 or "stale point-in-time" in str(w).lower()]
        if stale:
            problems.append(f"{entry['sid']} {d}: as_of {run.get('as_of')} — {stale[0][:160]}")
        out[d] = tgt
    return out, problems


def _row(sid: str, p: _Pos, new_id) -> list:
    return [new_id("pp"), sid, p.ticker, p.status, p.entry_date, p.entry, p.stop, p.target,
            p.weight, p.shares, p.last_price, p.last_date, p.exit_date, p.exit, p.return_pct,
            p.r_multiple, p.reason, p.created_at, p.planned_capital, "replay"]


def summarize(b: _Book) -> dict:
    priced = [p for p in b.positions if p.status in ("open", "closed") and p.entry]
    gross = sum(((p.exit if p.exit is not None else p.last_price) - p.entry) * p.shares
                for p in priced)
    return {"rebalances": len(b.runs), "positions": len(b.positions),
            "open": sum(p.status == "open" for p in b.positions),
            "closed": sum(p.status == "closed" for p in b.positions),
            "pending": sum(p.status == "pending" for p in b.positions),
            "void": sum(p.status == "void" for p in b.positions),
            "gross_pnl": round(gross, 2), "gross_return": round(gross / b.notional, 6),
            "cash_now": round(_available_cash(b), 2),
            "first_rebalance": str(b.runs[0]["ran_at"]) if b.runs else None,
            "last_rebalance": str(b.runs[-1]["ran_at"]) if b.runs else None,
            "holdings": sorted(p.ticker for p in b.positions if p.status in ("open", "pending"))}


def replay_paper(start: dt.date = REPLAY_START, end: dt.date | None = None,
                 notional: float | None = None, apply: bool = False) -> dict:
    """Replay every roster book from `start`; with apply=True archive and replace their history."""
    from ..data import trendlyne_store as ts
    from ..store_meta import _init, new_id
    from .rebalance import BOOK_NOTIONAL, ROSTER, _cadence

    end = end or dt.date.today()
    notional = float(notional or BOOK_NOTIONAL)
    plans, problems = {}, []
    for entry in ROSTER:
        cadence = _cadence(entry)
        days = rebalance_days(cadence, start, end)
        targets, probs = _targets_for(entry, days)
        problems += probs
        plans[entry["sid"]] = (cadence, targets)

    tickers = sorted({tk for _, tg in plans.values() for t in tg.values() for tk in t})
    pstart = (start - dt.timedelta(days=_LOOKBACK_DAYS)).isoformat()
    closes = ts.adjusted_close_panel(tickers, start=pstart, end=None, extend_live=True)
    opens = ts.adjusted_close_panel(tickers, start=pstart, end=None, field="open",
                                    extend_live=True)
    missing = sorted(set(tickers) - set(closes.columns))
    if missing:
        problems.append(f"no price column for {len(missing)} selected name(s): "
                        f"{', '.join(missing[:12])}")

    books = {sid: simulate_book(sid, notional, cad, tg, opens, closes, start, end)
             for sid, (cad, tg) in plans.items()}
    result = {"start": str(start), "end": str(end), "notional": notional, "applied": False,
              "problems": problems,
              "books": {sid: summarize(b) for sid, b in books.items()}}
    if not apply:
        return result
    if problems:
        raise ValueError("replay refused — fix these first: " + " | ".join(problems[:6]))

    from ..data.store import _LOCK

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    sids = list(books)
    ph = ",".join("?" * len(sids))
    con = _init()
    # The meta store is ONE process-wide connection shared by every request thread; a transaction
    # on it would swallow any other thread's statement issued in between. Hold the store's lock
    # across the whole archive-delete-insert so the swap is atomic to the rest of the API.
    _LOCK.acquire()
    try:
        con.execute("BEGIN TRANSACTION")
        con.execute(f"CREATE TABLE paper_positions_archive_{stamp} AS SELECT * FROM paper_positions")
        con.execute(f"CREATE TABLE paper_rebalance_runs_archive_{stamp} AS "
                    f"SELECT * FROM paper_rebalance_runs")
        con.execute(f"DELETE FROM paper_positions WHERE strategy_id IN ({ph})", sids)
        con.execute(f"DELETE FROM paper_rebalance_runs WHERE strategy_id IN ({ph})", sids)
        n_pos = n_run = 0
        for sid, b in books.items():
            for p in b.positions:
                con.execute(
                    "INSERT INTO paper_positions (id,strategy_id,ticker,status,entry_date,entry,"
                    "stop,target,weight,shares,last_price,last_date,exit_date,exit,return_pct,"
                    "r_multiple,reason,created_at,planned_capital,origin) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", _row(sid, p, new_id))
                n_pos += 1
            for r in b.runs:
                con.execute(
                    "INSERT INTO paper_rebalance_runs (id,strategy_id,ran_at,cadence,notional,"
                    "target_n,closed,opened,created_at,origin) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [new_id("prr"), sid, r["ran_at"], r["cadence"], r["notional"],
                     r["target_n"], r["closed"], r["opened"], r["created_at"], "replay"])
                n_run += 1
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        _LOCK.release()
        con.close()
    result.update({"applied": True, "archive_suffix": stamp,
                   "rows_written": {"paper_positions": n_pos, "paper_rebalance_runs": n_run}})
    return result
