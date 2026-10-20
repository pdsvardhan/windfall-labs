"""NSE corporate actions — the authoritative split / bonus / consolidation / demerger list (iter-199, #952).

Why this exists. Live names are priced from Trendlyne's split-adjusted `ohlcv` up to its last
harvested bar, then from RAW NSE Bhavcopy after it (adjusted_close_panel's live splice). A split or
bonus whose ex-date falls in that raw tail reads as a 50-90% overnight crash to signals, stops,
marks and the market-cap fallback until the next Trendlyne harvest re-adjusts history. Nothing we
already held could tell such a step from a real crash: Trendlyne's `corporate_actions` export
carries dividends/bonus/rights only, and Bhavcopy's `prev_close` is not adjusted reliably (it was
for CCAVENUE's consolidation, not for BHAGYANGR). NSE's own corporate-actions API is reachable
from the server and names each event, so it is the source.

What it is used for, and the convention. Only events whose PRICE RATIO is stated are adjusted —
splits ("From Rs 10/- To Rs 2/-" -> 5), bonuses ("a:b" -> (a+b)/b) and consolidations (ratio < 1).
That is exactly the set Trendlyne back-adjusts (measured 2026-10-20: TEMBO 1:10 -> x0.1, GOODLUCK
bonus 2:1 -> x1/3, TRENT bonus 1:2 -> x2/3), so the tail matches what Trendlyne will publish and
nothing moves when it catches up. Demergers and schemes are kept as typed events with no ratio:
Trendlyne leaves them unadjusted (GUJENERGY, TRIVENI, INOXGREEN), and so does every backtest.

Fetched in-process by the api, which owns the windfall.duckdb write lock (adr-018 ONE DOOR).
"""
from __future__ import annotations

import datetime as dt
import logging
import re

import requests

from .store import connect
from .surveillance import _HEADERS

_log = logging.getLogger(__name__)

LANDING = "https://www.nseindia.com/companies-listing/corporate-filings-actions"
API = "https://www.nseindia.com/api/corporates-corporateActions"

SCHEMA = """
CREATE TABLE IF NOT EXISTS nse_corporate_actions (
    symbol VARCHAR NOT NULL, ex_date DATE NOT NULL, subject VARCHAR NOT NULL,
    kind VARCHAR NOT NULL, ratio DOUBLE, record_date DATE, fetched_at TIMESTAMP,
    PRIMARY KEY (symbol, ex_date, subject)
);
"""

_RS = r"(?:Rs|Re)\.?\s*([\d.]+)"
_SPLIT = re.compile(r"Split.*?From\s+" + _RS + r".*?To\s+" + _RS, re.I)
_CONSOL = re.compile(r"Consolidat.*?From\s+" + _RS + r".*?To\s+" + _RS, re.I)
_BONUS = re.compile(r"^\s*Bonus\s+(\d+)\s*:\s*(\d+)", re.I)


def parse(subject: str) -> tuple[str | None, float | None]:
    """(kind, price ratio) for an NSE corporate-action subject; (None, None) when irrelevant.

    ratio is how many post-event shares one pre-event share becomes — the factor the price falls
    by on the ex-date. None for demergers/schemes, whose price effect is not stated.
    """
    s = subject or ""
    m = _SPLIT.search(s)
    if m:
        old, new = float(m.group(1)), float(m.group(2))
        return ("split", old / new) if old > 0 and new > 0 else ("split", None)
    m = _CONSOL.search(s)
    if m:
        old, new = float(m.group(1)), float(m.group(2))
        return ("consolidation", old / new) if old > 0 and new > 0 else ("consolidation", None)
    m = _BONUS.search(s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return ("bonus", (a + b) / b) if b > 0 else ("bonus", None)
    low = s.lower()
    if "demerger" in low:
        return "demerger", None
    if "scheme of arrangement" in low:
        return "scheme", None
    return None, None


def _date(x) -> dt.date | None:
    try:
        return dt.datetime.strptime(str(x).strip(), "%d-%b-%Y").date()
    except ValueError:
        return None


def fetch(from_date: dt.date, to_date: dt.date) -> list[dict]:
    """Every NSE equity corporate action with an ex-date in [from_date, to_date], relevant kinds only."""
    s = requests.Session()
    s.headers.update(_HEADERS)
    s.headers["Referer"] = LANDING
    s.get(LANDING, timeout=30)           # NSE's API answers only with the landing page's cookies
    r = s.get(API, params={"index": "equities", "from_date": from_date.strftime("%d-%m-%Y"),
                           "to_date": to_date.strftime("%d-%m-%Y")}, timeout=60)
    r.raise_for_status()
    out = []
    for x in r.json():
        kind, ratio = parse(x.get("subject") or "")
        exd = _date(x.get("exDate"))
        if kind is None or exd is None or not x.get("symbol"):
            continue
        out.append({"symbol": str(x["symbol"]).strip().upper(), "ex_date": exd,
                    "subject": (x.get("subject") or "").strip(), "kind": kind, "ratio": ratio,
                    "record_date": _date(x.get("recDate"))})
    return out


MIN_KEEP = 0.8   # a window fetch returning under 80% of what the window already holds is refused


def ingest(rows: list[dict], window: tuple[dt.date, dt.date] | None = None) -> dict:
    """Upsert rows. With `window`, the fetch is authoritative for that ex-date range: everything
    stored inside it is replaced, so an event NSE revised (subject or ex-date) leaves no stale twin
    to be applied twice. The swap is one transaction under the store lock.

    Replacing on a bad fetch would be worse than not refreshing: an HTTP 200 carrying [] or a
    truncated list would delete the events and bring every phantom crash back (verifier finding
    N1). Events only enter a rolling window, they do not vanish from it, so a fetch that comes back
    materially SHORTER than what the window holds is refused and the stored list kept.
    """
    from .store import _LOCK

    con = connect()
    con.execute(SCHEMA)
    if window:
        held = con.execute("SELECT count(*) FROM nse_corporate_actions WHERE ex_date BETWEEN ? AND ?",
                           list(window)).fetchone()[0]
        if held and len(rows) < MIN_KEEP * held:
            raise ValueError(f"refusing to replace {held} stored corporate actions in "
                             f"{window[0]}..{window[1]} with a fetch of {len(rows)} — kept the stored list")
    now = dt.datetime.now()
    with _LOCK:
        con.execute("BEGIN TRANSACTION")
        try:
            if window:
                con.execute("DELETE FROM nse_corporate_actions WHERE ex_date BETWEEN ? AND ?",
                            list(window))
            for r in rows:
                con.execute("INSERT OR REPLACE INTO nse_corporate_actions VALUES (?,?,?,?,?,?,?)",
                            [r["symbol"], r["ex_date"], r["subject"], r["kind"], r.get("ratio"),
                             r.get("record_date"), now])
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    by_kind: dict[str, int] = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    return {"count": len(rows), "by_kind": by_kind}


def refresh(days_back: int = 150, days_forward: int = 60) -> dict:
    """Fetch a rolling window (announced events have future ex-dates) and upsert it."""
    today = dt.date.today()
    window = (today - dt.timedelta(days=days_back), today + dt.timedelta(days=days_forward))
    rows = fetch(*window)
    return {"window": [str(window[0]), str(window[1])], **ingest(rows, window)}


def _rows(symbols, where: str) -> list[tuple]:
    syms = sorted({str(s).upper() for s in symbols})
    if not syms:
        return []
    try:
        con = connect()
        con.execute(SCHEMA)
        return con.execute(
            "SELECT symbol, ex_date, ratio, kind, subject FROM nse_corporate_actions "
            f"WHERE {where} AND symbol IN ({','.join(['?'] * len(syms))}) ORDER BY ex_date",
            syms).fetchall()
    except Exception as exc:  # noqa: BLE001 — never let the CA list take the price layer down, but say so
        _log.warning("corporate actions unavailable: %r", exc)
        return []


def ratio_events(symbols) -> dict[str, list[tuple[dt.date, float]]]:
    """{symbol: [(ex_date, ratio), ...]} — the price-adjusting events (split/bonus/consolidation)."""
    out: dict[str, list] = {}
    for sym, exd, ratio, _kind, _subj in _rows(symbols, "ratio IS NOT NULL AND ratio > 0 AND ratio <> 1"):
        out.setdefault(sym, []).append((exd, float(ratio)))
    return out


def demergers(symbols) -> dict[str, list[tuple[dt.date, str]]]:
    """{symbol: [(ex_date, subject), ...]} — events that move the price with no stated ratio."""
    out: dict[str, list] = {}
    for sym, exd, _ratio, _kind, subj in _rows(symbols, "kind IN ('demerger', 'scheme')"):
        out.setdefault(sym, []).append((exd, subj))
    return out
