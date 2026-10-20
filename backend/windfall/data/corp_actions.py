"""NSE corporate actions — the authoritative split / bonus / consolidation / rights / demerger list
(iter-199 #952; full history and rights since iter-204, adr-050).

Why this exists. Live names are priced from Trendlyne's split-adjusted `ohlcv` up to its last
harvested bar, then from RAW NSE Bhavcopy after it (adjusted_close_panel's live splice). Since
adr-050 that harvest is frozen, so every corporate action after it lands in the raw tail, and
names Trendlyne never priced at all (new listings, the companies it never listed) are priced from
Bhavcopy for their whole history. A split, bonus or rights issue in raw Bhavcopy reads as an
overnight crash. NSE's own corporate-actions API names each event, so it is the source.

What it is used for, and the convention. Events with a PRICE RATIO are adjusted — splits
("From Rs 10/- To Rs 2/-" -> 5), bonuses ("a:b" -> (a+b)/b), consolidations (ratio < 1), pre-2018
subjects that combine events ("Bonus 1:1 / Face Value Split From Rs.10/- To Re.1/-" -> both,
multiplied; #958), and rights issues priced below the market: the standard theoretical ex-rights
price, TERP = (b*P + a*S) / (a+b) for "a new for b held" at S = face value + premium with P the
last close before the ex-date, ratio P / TERP. That is the set Trendlyne back-adjusts (measured
iter-199/200: TEMBO 1:10 -> x0.1, GOODLUCK bonus 2:1 -> x1/3, GENESYS rights -> x0.682). Demergers
and schemes are kept as typed events with no ratio: Trendlyne leaves them unadjusted (GUJENERGY,
TRIVENI, INOXGREEN), and so does every backtest.

Fetched in-process by the api, which owns the windfall.duckdb write lock (adr-018 ONE DOOR).
"""
from __future__ import annotations

import datetime as dt
import logging
import math
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
ALTER TABLE nse_corporate_actions ADD COLUMN IF NOT EXISTS face_value DOUBLE;
"""

_RS = r"(?:Rs|Re)\.?\s*([\d.]+)"
_SPLIT = re.compile(r"Split.*?From\s+" + _RS + r".*?To\s+" + _RS, re.I)
_CONSOL = re.compile(r"Consolidat.*?From\s+" + _RS + r".*?To\s+" + _RS, re.I)
_BONUS = re.compile(r"^\s*Bonus\s+(\d+)\s*:\s*(\d+)", re.I)
# "/" joins two events but also appears inside "Rs 10/- Per Share": only a slash NOT followed by
# "-" separates (iter-200 measurement, 27 combined subjects 2010-2018).
_SEP = re.compile(r"\s*(?:/(?!-)|\band\b|&|\+)\s*", re.I)

# Rights. NSE writes the same event many ways: "Rights 1:5 @ Premium Rs 45/-", "Rights 2:3@Prem
# Rs.345/-", "Rights Issue - 3:5 @ Premium Rs.93/-", "Rights At 2:1 At A Premium Of Rs.39.50",
# "Rights 7:10 @ Prm Rs 102/-", "Rights - 2:3@ Par Rs 10", "Rights : 24:10 At Par", "Rights
# 1:11.10 @ Premium Rs 0". A ratio with no stated price ("Rights 2:7") cannot be priced and is kept
# as an unpriced rights event; so are partly-paid issues and debenture/warrant-only rights.
_IS_RIGHTS = re.compile(r"^\s*Rights\b|\bRights\s+Issue\b|Ratio\s+Of\s+The\s+Rights", re.I)
_RIGHTS_RATIO = re.compile(r"Rights\b[^0-9]{0,20}?(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", re.I)
_RIGHTS_RATIO_ALT = re.compile(r"Ratio\s+Of\s+The\s+Rights\s+Is\s+(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", re.I)
_RIGHTS_PREM = re.compile(r"\b(?:Premium|Prem|Prm)\b\.?\s*(?:Of\s+)?(?:Rs|Re)?\.?\s*([\d.]+)", re.I)
_RIGHTS_PAR = re.compile(r"(?:@|\bAt)\s*Par\b", re.I)
_RIGHTS_SKIP = re.compile(r"Partly|Debenture|\bNcd\b|\bCcd|\bCcps\b|Entitlement", re.I)


def parse(subject: str) -> tuple[str | None, float | None]:
    """(kind, price ratio) for ONE NSE corporate-action event; (None, None) when irrelevant.

    ratio is how many post-event shares one pre-event share becomes — the factor the price falls
    by on the ex-date. None for demergers/schemes, whose price effect is not stated, and for rights,
    whose ratio needs a price (see parse_rights / rights_ratio).
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
    if _IS_RIGHTS.search(s):
        return "rights", None
    low = s.lower()
    if "demerger" in low:
        return "demerger", None
    if "scheme of arrangement" in low:
        return "scheme", None
    return None, None


def parse_all(subject: str) -> tuple[str | None, float | None]:
    """(kinds, ratio) of a WHOLE subject: every event in it, ratios multiplied (#958).

    A rights issue is recognised on the whole subject first, because its own text carries "/-",
    "&" and "and" ("... @ Premium Rs.715 Per Share And 3 Warrants : 1 Eq") that would otherwise be
    split into fragments. kinds joins the distinct kinds with "+" ("bonus+split").
    """
    s = subject or ""
    if _IS_RIGHTS.search(s) and not _BONUS.search(s) and not _SPLIT.search(s):
        return "rights", None
    parts = [parse(p) for p in _SEP.split(s)]
    kinds = sorted({k for k, _r in parts if k})
    if not kinds:
        return None, None
    ratios = [r for _k, r in parts if r]
    return "+".join(kinds), (math.prod(ratios) if ratios else None)


def parse_rights(subject: str) -> tuple[float, float, float] | None:
    """(a, b, premium) for "a new shares for every b held at face value + premium"; None when the
    subject states no price, or the issue is partly paid or not equity (it cannot be priced)."""
    s = subject or ""
    if _RIGHTS_SKIP.search(s):
        return None
    m = _RIGHTS_RATIO.search(s) or _RIGHTS_RATIO_ALT.search(s)
    if not m:
        return None
    a, b = float(m.group(1)), float(m.group(2))
    if a <= 0 or b <= 0:
        return None
    p = _RIGHTS_PREM.search(s[m.end():]) or _RIGHTS_PREM.search(s)
    if p:
        try:
            return a, b, float(p.group(1).rstrip("."))
        except ValueError:
            return None
    if _RIGHTS_PAR.search(s):
        return a, b, 0.0
    return None


def rights_ratio(subject: str, face_value: float | None, cum_close: float | None) -> float | None:
    """P / TERP for a rights issue priced below the market, else None (no dilution to adjust)."""
    t = parse_rights(subject)
    if t is None or not face_value or not cum_close or cum_close <= 0:
        return None
    a, b, prem = t
    s = face_value + prem
    if s >= cum_close:
        return None
    terp = (b * cum_close + a * s) / (a + b)
    return cum_close / terp


def _date(x) -> dt.date | None:
    try:
        return dt.datetime.strptime(str(x).strip(), "%d-%b-%Y").date()
    except ValueError:
        return None


def _float(x) -> float | None:
    try:
        v = float(str(x).strip())
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def fetch(from_date: dt.date, to_date: dt.date) -> list[dict]:
    """Every NSE equity corporate action with an ex-date in [from_date, to_date], relevant kinds only."""
    s = requests.Session()
    s.headers.update(_HEADERS)
    s.headers["Referer"] = LANDING
    s.get(LANDING, timeout=30)           # NSE's API answers only with the landing page's cookies
    r = s.get(API, params={"index": "equities", "from_date": from_date.strftime("%d-%m-%Y"),
                           "to_date": to_date.strftime("%d-%m-%Y")}, timeout=90)
    r.raise_for_status()
    out = []
    for x in r.json():
        subject = (x.get("subject") or "").strip()
        kind, ratio = parse_all(subject)
        exd = _date(x.get("exDate"))
        if kind is None or exd is None or not x.get("symbol"):
            continue
        out.append({"symbol": str(x["symbol"]).strip().upper(), "ex_date": exd,
                    "subject": subject, "kind": kind, "ratio": ratio,
                    "record_date": _date(x.get("recDate")), "face_value": _float(x.get("faceVal"))})
    return out


def price_rights(rows: list[dict], last_close_before=None) -> int:
    """Fill each rights row's ratio from the last close before its ex-date (rows priced in place).

    Computed when the list is refreshed, not when it is read, so every reader — the price tail,
    Bhavcopy-priced names, the paper re-base — sees one stored number. A future ex-date has no
    such close yet and stays unpriced until a refresh after it (the 9:00 cron, on the ex-date,
    already has the previous session's close).
    """
    if last_close_before is None:
        from .trendlyne_store import last_raw_close_before as last_close_before
    priced = 0
    for r in rows:
        if r["kind"] != "rights":
            continue
        if r["ex_date"] > dt.date.today():
            continue
        try:
            p = last_close_before(r["symbol"], r["ex_date"])
        except Exception as exc:  # noqa: BLE001 — an unpriced rights row is safe (no adjustment)
            _log.warning("rights pricing failed for %s %s: %r", r["symbol"], r["ex_date"], exc)
            p = None
        r["ratio"] = rights_ratio(r["subject"], r.get("face_value"), p)
        priced += r["ratio"] is not None
    return priced


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
                con.execute(
                    "INSERT OR REPLACE INTO nse_corporate_actions (symbol, ex_date, subject, kind, "
                    "ratio, record_date, fetched_at, face_value) VALUES (?,?,?,?,?,?,?,?)",
                    [r["symbol"], r["ex_date"], r["subject"], r["kind"], r.get("ratio"),
                     r.get("record_date"), now, r.get("face_value")])
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
    priced = price_rights(rows)
    return {"window": [str(window[0]), str(window[1])], "rights_priced": priced, **ingest(rows, window)}


def backfill(from_year: int = 2010, to_year: int | None = None) -> dict:
    """The full history, one calendar year per fetch (adr-050): names priced from Bhavcopy for
    their whole life need every event, not just the rolling window. Each year is its own
    authoritative window, so a short year is refused exactly as a short daily refresh is."""
    to_year = to_year or dt.date.today().year
    out = {}
    for y in range(from_year, to_year + 1):
        window = (dt.date(y, 1, 1), dt.date(y, 12, 31))
        rows = fetch(*window)
        priced = price_rights(rows)
        out[str(y)] = {"rights_priced": priced, **ingest(rows, window)}
    return out


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


def _events(symbols, include_rights: bool) -> dict[str, list[tuple[dt.date, float]]]:
    where = "ratio IS NOT NULL AND ratio > 0 AND ratio <> 1"
    if not include_rights:
        where += " AND kind <> 'rights'"
    out: dict[str, list] = {}
    seen: set = set()
    for sym, exd, ratio, kind, _subj in _rows(symbols, where):
        # One event filed twice under two wordings is the same symbol, day, KIND and ratio. A bonus
        # 1:1 and a split 10->5 on one day are two events that happen to share the ratio 2 — both
        # apply (x4). Seven such pairs since 2021 (GPIL, 360ONE, MAANALU, CGCL, LINC, NAZARA,
        # BHARATRAS; iter-204 verifier B1); deduping on (day, ratio) alone left a phantom 50% crash.
        key = (sym, exd, float(ratio), kind)
        if key in seen:
            continue
        seen.add(key)
        out.setdefault(sym, []).append((exd, float(ratio)))
    return out


def ratio_events(symbols) -> dict[str, list[tuple[dt.date, float]]]:
    """{symbol: [(ex_date, ratio), ...]} — the PRICE-adjusting events: splits, bonuses,
    consolidations, combined subjects and rights issues priced below the market (P/TERP)."""
    return _events(symbols, include_rights=True)


def share_events(symbols) -> dict[str, list[tuple[dt.date, float]]]:
    """Like ratio_events but for a share COUNT: split/bonus/consolidation only. A rights issue's
    P/TERP is a price adjustment; the shares it adds ((a+b)/b, for new money) are a different
    number, so the market-cap fallback that scales shares must not use it."""
    return _events(symbols, include_rights=False)


def demergers(symbols) -> dict[str, list[tuple[dt.date, str]]]:
    """{symbol: [(ex_date, subject), ...]} — events that move the price with no stated ratio."""
    out: dict[str, list] = {}
    for sym, exd, _ratio, _kind, subj in _rows(symbols, "(kind LIKE '%demerger%' OR kind LIKE '%scheme%')"):
        out.setdefault(sym, []).append((exd, subj))
    return out
