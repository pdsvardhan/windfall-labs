"""iter-206 (#970): quarterly results from NSE's own filings -> a point-in-time trailing-twelve-month EPS.

Why: Trendlyne's daily TTM P/E covers survivors only and needs a browser harvest; the screener.in P/E is
annual and up to 16 months stale. NSE publishes every listed company's quarterly results as XBRL with a
broadcast timestamp, so each figure has the date the market could first have known it:

  legacy endpoint      /api/corporates-financial-results      quarters to Dec 2024 (XBRL from 2017-18)
  integrated endpoint  /api/integrated-filing-results         2025 onward (raw XBRL under `xbrl`)

Both carry the same SEBI/BSE tags and the same two contexts: OneD = the quarter, FourD = the fiscal
year to date. This module fetches, parses and stores them (research store only — nothing here is a
factor the engine reads; see ttm_eps / pe_ttm_panel for the research series).

  data/nse_filings.duckdb   filings(symbol, period_end, basis)  one row per quarter and basis,
                            the EARLIEST broadcast kept (the first moment it was knowable)
                            fetch_log(symbol)                   resumable per-symbol state

ONE DOOR (adr-018): a standalone DB with a single writer (the fetch process); the api never attaches it.

CLI:  python -m windfall.data.nse_filings fetch --symbols-file f.csv [--limit N] [--throttle 1.0]
      python -m windfall.data.nse_filings status
      python -m windfall.data.nse_filings reparse      # rebuild `filings` from data/nse_filings_raw/ after a parser fix
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import logging
import re
import time

import duckdb
import pandas as pd
import requests

from ..config import DATA_DIR
from .surveillance import _HEADERS

_log = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "nse_filings.duckdb"
RAW_DIR = DATA_DIR / "nse_filings_raw"      # every fetched filing, gzipped, so a parser fix never needs a refetch
LEGACY_LANDING = "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"
LEGACY_API = "https://www.nseindia.com/api/corporates-financial-results"
INTEGRATED_LANDING = "https://www.nseindia.com/companies-listing/corporate-integrated-filing"
INTEGRATED_API = "https://www.nseindia.com/api/integrated-filing-results"

SCHEMA = """
CREATE TABLE IF NOT EXISTS filings (
  symbol VARCHAR, period_end DATE, basis VARCHAR, source VARCHAR, period_months INTEGER,
  broadcast_ts TIMESTAMP, audited VARCHAR, taxonomy VARCHAR,
  np DOUBLE, np_owners DOUBLE, eps_basic DOUBLE, eps_diluted DOUBLE, revenue DOUBLE,
  paid_up DOUBLE, face_value DOUBLE,
  ytd_months INTEGER, np_ytd DOUBLE, eps_ytd DOUBLE,
  url VARCHAR, fetched_at TIMESTAMP,
  PRIMARY KEY (symbol, period_end, basis)
);
CREATE TABLE IF NOT EXISTS fetch_log (
  symbol VARCHAR PRIMARY KEY, status VARCHAR, n_listed INTEGER, n_new INTEGER, n_failed INTEGER,
  detail VARCHAR, logged_at TIMESTAMP
);
"""

# Tag candidates, best first. Industrial companies, banks and the integrated-filing taxonomy spell the
# same quantities differently (checked on TCS, HDFCBANK, KAMDHENU, SHANTIGOLD, Oct 2026).
NP_TAGS = ("ProfitLossForPeriod", "ProfitLossForThePeriod", "ProfitLossForPeriodFromContinuingOperations",
           "ProfitLossFromOrdinaryActivitiesAfterTax")
NP_OWNERS_TAGS = ("ProfitOrLossAttributableToOwnersOfParent", "ProfitLossAttributableToOwnersOfParent",
                  "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates")
EPS_BASIC_TAGS = ("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                  "BasicEarningsPerShareAfterExtraordinaryItems",
                  "BasicEarningsLossPerShareFromContinuingOperations",
                  "BasicEarningsPerShareBeforeExtraordinaryItems")
EPS_DILUTED_TAGS = ("DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                    "DilutedEarningsPerShareAfterExtraordinaryItems",
                    "DilutedEarningsLossPerShareFromContinuingOperations",
                    "DilutedEarningsPerShareBeforeExtraordinaryItems")
_B_CONT, _B_DISC = ("BasicEarningsLossPerShareFromContinuingOperations",
                    "BasicEarningsLossPerShareFromDiscontinuedOperations")
_D_CONT, _D_DISC = ("DilutedEarningsLossPerShareFromContinuingOperations",
                    "DilutedEarningsLossPerShareFromDiscontinuedOperations")
REVENUE_TAGS = ("RevenueFromOperations", "InterestEarned", "Income")
PAID_UP_TAGS = ("PaidUpValueOfEquityShareCapital",)
FACE_VALUE_TAGS = ("FaceValueOfEquityShareCapital",)

# NSE's legacy listing calls a standalone filing "Non-Consolidated"; the integrated one says "Standalone".
_BASIS = {"consolidated": "consolidated", "standalone": "standalone", "non-consolidated": "standalone"}

_FACT = re.compile(r"<(?:[A-Za-z0-9\-]+):([A-Za-z0-9_]+)\b([^>]*)>([^<]*)<")
_CTX = re.compile(r"<xbrli:context\b[^>]*\bid=\"([^\"]+)\"[^>]*>(.*?)</xbrli:context>", re.S)
_REF = re.compile(r"contextRef=\"([^\"]+)\"")
_START = re.compile(r"<xbrli:startDate>\s*([0-9\-]+)\s*<")
_END = re.compile(r"<xbrli:endDate>\s*([0-9\-]+)\s*<")


def _num(s: str):
    try:
        return float(s.strip().replace(",", ""))
    except ValueError:
        return None


def _months(start: dt.date, end: dt.date) -> int:
    return int(round(((end - start).days + 1) / 30.4375))


def parse_xbrl(text: str, hint: tuple | None = None) -> dict | None:
    """One filing -> {period_end, period_months, ytd_months, np, np_owners, eps_basic, eps_diluted,
    revenue, paid_up, face_value, np_ytd, eps_ytd, taxonomy} or None when it is not a results XBRL.

    OneD is the reporting quarter and FourD the year to date, in both taxonomies. Values are absolute
    rupees (not crore) and per-share rupees.

    `hint` = (from_date, to_date) from the filing's listing row, used only when the file declares no
    dated context at all (some 2019-2020 filings; DEEPENR Sep-2019)."""
    ctx: dict[str, tuple[dt.date, dt.date]] = {}
    dims: dict[str, list] = {"OneD": [], "FourD": []}
    for cid, body in _CTX.findall(text):
        a, b = _START.search(body), _END.search(body)
        if not (a and b):
            continue
        span = (dt.date.fromisoformat(a.group(1)), dt.date.fromisoformat(b.group(1)))
        if cid in ("OneD", "FourD"):
            ctx[cid] = span
        elif cid.endswith("D") and cid.startswith("One"):
            dims["OneD"].append(span)       # a dimensional context of the quarter ("OneOperatingExpenses01D")
        elif cid.endswith("D") and cid.startswith("Four"):
            dims["FourD"].append(span)
    # Filings of 2017 to mid-2022 often reference OneD/FourD without defining them; the quarter's dates
    # are still readable from the dimensional contexts that share its period (checked on TCS 2019).
    for k, spans in dims.items():
        if k not in ctx and spans:
            ctx[k] = max(set(spans), key=spans.count)
    if "OneD" not in ctx and hint and hint[1]:
        ctx["OneD"] = (hint[0] or hint[1] - dt.timedelta(days=90), hint[1])
    if "OneD" not in ctx:
        return None
    facts: dict[tuple[str, str], float] = {}
    for tag, attrs, val in _FACT.findall(text):
        ref = _REF.search(attrs)
        if not ref or ref.group(1) not in ("OneD", "FourD"):
            continue
        v = _num(val)
        if v is not None:
            facts.setdefault((tag, ref.group(1)), v)

    def pick(tags, c):
        for t in tags:
            if (t, c) in facts:
                return facts[(t, c)]
        return None

    def eps(tags, cont_tag, disc_tag, c):
        """Per-share earnings. Some filers tag the discontinued-operations EPS with the continuing figure
        although they have none, and the 'continuing and discontinued' total then arrives as their sum -
        twice the real EPS (ADANIENT Sep-2022, 3MINDIA Sep-2025). That pattern is read as the continuing EPS."""
        v = pick(tags, c)
        cont, disc = facts.get((cont_tag, c)), facts.get((disc_tag, c))
        if (v is not None and cont is not None and disc is not None and abs(disc) > 1e-9
                and abs(v - (cont + disc)) <= 0.011 and abs(cont - disc) <= 0.011):
            return cont
        return v

    start, end = ctx["OneD"]
    out = {
        "period_end": end, "period_months": _months(start, end),
        "ytd_months": _months(*ctx["FourD"]) if "FourD" in ctx else None,
        "np": pick(NP_TAGS, "OneD"), "np_owners": pick(NP_OWNERS_TAGS, "OneD"),
        "eps_basic": eps(EPS_BASIC_TAGS, _B_CONT, _B_DISC, "OneD"),
        "eps_diluted": eps(EPS_DILUTED_TAGS, _D_CONT, _D_DISC, "OneD"),
        "revenue": pick(REVENUE_TAGS, "OneD"),
        "paid_up": pick(PAID_UP_TAGS, "OneD"), "face_value": pick(FACE_VALUE_TAGS, "OneD"),
        "np_ytd": pick(NP_TAGS, "FourD"), "eps_ytd": eps(EPS_BASIC_TAGS, _B_CONT, _B_DISC, "FourD"),
        "taxonomy": "banking" if ("InterestEarned", "OneD") in facts else "industrial",
    }
    if out["np"] is None and out["eps_basic"] is None:
        return None
    return out


# ── listings -> which filings to fetch ──────────────────────────────────────────────────────────

def _d(s, fmt):
    try:
        return dt.datetime.strptime(str(s).strip(), fmt)
    except (TypeError, ValueError):
        return None


_SEEN_LABELS: set = set()


def select_filings(legacy: list[dict], integrated: list[dict]) -> list[dict]:
    """Both listings -> one candidate per (period_end, basis): the earliest broadcast, non-cumulative,
    with a raw XBRL link. Then ONE basis per period: consolidated where the company filed it, else
    standalone (a consolidated + standalone pair is fetched once)."""
    cands = []
    for r in legacy:
        url = str(r.get("xbrl") or "")
        pe = _d(r.get("toDate"), "%d-%b-%Y")
        bc = _d(r.get("broadCastDate"), "%d-%b-%Y %H:%M:%S") or _d(r.get("exchdisstime"), "%d-%b-%Y %H:%M:%S")
        if not url.lower().endswith(".xml") or pe is None or bc is None:
            continue
        if str(r.get("cumulative") or "").lower().startswith("cum"):   # "Cumulative" = a year-to-date filing
            continue
        fd = _d(r.get("fromDate"), "%d-%b-%Y")
        cands.append({"source": "legacy", "period_end": pe.date(), "from_date": fd.date() if fd else None, "basis": _BASIS.get(str(r.get("consolidated") or "").strip().lower(), ""),
                      "broadcast_ts": bc, "audited": r.get("audited"), "url": url})
    for r in integrated:
        url = str(r.get("xbrl") or "")
        pe = _d(r.get("qe_Date"), "%d-%b-%Y")
        bc = _d(r.get("broadcast_Date"), "%d-%b-%Y %H:%M:%S")
        if "financial" not in str(r.get("type") or "").lower() or not url.lower().endswith(".xml") \
                or pe is None or bc is None:
            continue
        cands.append({"source": "integrated", "period_end": pe.date(), "basis": _BASIS.get(str(r.get("consolidated") or "").strip().lower(), ""),
                      "broadcast_ts": bc, "audited": r.get("audited"), "url": url})
    best: dict[tuple, dict] = {}
    for c in cands:
        if c["basis"] not in ("consolidated", "standalone"):
            if c["basis"] not in _SEEN_LABELS:      # a spelling NSE has not used before: say so once, do not drop silently
                _SEEN_LABELS.add(c["basis"])
                _log.warning("filing with an unrecognised consolidated/standalone label %r dropped", c["basis"])
            continue
        k = (c["period_end"], c["basis"])
        if k not in best or c["broadcast_ts"] < best[k]["broadcast_ts"]:
            best[k] = c
    by_period: dict[dt.date, dict] = {}
    for (pe, basis), c in sorted(best.items()):
        if pe not in by_period or basis == "consolidated":
            by_period[pe] = c
    return [by_period[p] for p in sorted(by_period)]


# ── fetching ────────────────────────────────────────────────────────────────────────────────────

class Nse:
    """A throttled NSE session. NSE answers its API only with the landing page's cookies, which expire;
    a 401/403 or a body that is not JSON re-lands and retries."""

    def __init__(self, throttle: float = 1.0):
        self.throttle, self.s, self.landed, self.n = throttle, None, {}, 0
        self._new()

    def _new(self):
        self.s = requests.Session()
        self.s.headers.update(_HEADERS)
        self.landed = {}

    def _land(self, url):
        self.s.headers["Referer"] = url
        self.s.get(url, timeout=30)
        self.landed[url] = time.time()
        time.sleep(self.throttle)

    def get(self, url, landing, params=None, json_=True):
        last = None
        for attempt in range(4):
            if time.time() - self.landed.get(landing, 0) > 240 or attempt:
                if attempt >= 2:
                    self._new()
                try:
                    self._land(landing)
                except requests.RequestException as e:
                    last = e
                    time.sleep(3 * (attempt + 1))
                    continue
            try:
                r = self.s.get(url, params=params, timeout=60)
                time.sleep(self.throttle)
                self.n += 1
                if r.status_code == 200:
                    return r.json() if json_ else r.text
                last = RuntimeError(f"http {r.status_code}")
                if r.status_code == 404:
                    return [] if json_ else None
            except (requests.RequestException, ValueError) as e:
                last = e
            time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"giving up on {url}: {last}")


def _rows(x):
    return x.get("data", []) if isinstance(x, dict) else (x or [])


def connect(path=DB_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA)
    return con


def dates_agree(parsed_end: dt.date, listed_end: dt.date, tolerance_days: int = 30) -> bool:
    """A file whose own OneD quarter is not the quarter its listing row names (14 of 1,872 in the first
    106 companies, always by exactly a year: AARTIDRUGS Jun-2025 carries Jun-2024's contexts) cannot be
    trusted to say which quarter its numbers are. It is kept raw but not stored, so it can neither
    overwrite the real quarter nor stand in for a missing one."""
    return abs((parsed_end - listed_end).days) <= tolerance_days


def _save_raw(symbol: str, c: dict, text: str) -> None:
    d = RAW_DIR / symbol
    d.mkdir(parents=True, exist_ok=True)
    stem = f"{c['period_end']}_{c['basis']}"
    (d / f"{stem}.xml.gz").write_bytes(gzip.compress(text.encode("utf-8")))
    meta = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in c.items()}
    (d / f"{stem}.json").write_text(json.dumps(meta))


def _store(con, symbol: str, c: dict, p: dict) -> None:
    con.execute(
        "INSERT OR REPLACE INTO filings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [symbol, p["period_end"], c["basis"], c["source"], p["period_months"], c["broadcast_ts"],
         c["audited"], p["taxonomy"], p["np"], p["np_owners"], p["eps_basic"], p["eps_diluted"],
         p["revenue"], p["paid_up"], p["face_value"], p["ytd_months"], p["np_ytd"], p["eps_ytd"],
         c["url"], dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)])


def reparse(con) -> dict:
    """Rebuild `filings` from the saved raw files with the CURRENT parser (after a parser fix)."""
    ok = bad = 0
    for meta_path in sorted(RAW_DIR.glob("*/*.json")):
        symbol = meta_path.parent.name
        c = json.loads(meta_path.read_text())
        c["period_end"] = dt.date.fromisoformat(c["period_end"])
        c["from_date"] = dt.date.fromisoformat(c["from_date"]) if c.get("from_date") else None
        c["broadcast_ts"] = dt.datetime.fromisoformat(c["broadcast_ts"])
        text = gzip.decompress(meta_path.with_suffix(".xml.gz").read_bytes()).decode("utf-8")
        p = parse_xbrl(text, (c["from_date"], c["period_end"]))
        if p is None or not dates_agree(p["period_end"], c["period_end"]):
            bad += 1
            continue
        _store(con, symbol, c, p)
        ok += 1
    return {"reparsed": ok, "unparseable": bad}


def fetch_symbol(con, nse: Nse, symbol: str, alts=()) -> dict:
    """List, select and store the quarters of one symbol that are not yet in the store.

    `alts` are the other tickers the company has used (same ISIN): NSE answers by the CURRENT symbol,
    so an engine symbol that has since been renamed (ZOMATO -> ETERNAL) returns nothing. Every
    candidate is asked and the listings are merged; a quarter filed under both is kept once."""
    legacy, integrated = [], []
    for sym in dict.fromkeys([symbol, *alts]):
        for attempt in range(2):
            legacy += _rows(nse.get(LEGACY_API, LEGACY_LANDING, {"index": "equities", "symbol": sym, "period": "Quarterly"}))
            integrated += _rows(nse.get(INTEGRATED_API, INTEGRATED_LANDING, {"index": "equities", "symbol": sym}))
            if legacy or integrated:
                break
            if attempt == 0:      # an expired session answers 200 with nothing: re-land once before believing "empty"
                nse.landed = {}
        if legacy or integrated:
            break      # the first ticker that answers is the company's current one
    chosen = select_filings(legacy, integrated)
    have = {r[0] for r in con.execute("SELECT period_end FROM filings WHERE symbol = ?", [symbol]).fetchall()}
    new = failed = 0
    detail = []
    for c in chosen:
        if c["period_end"] in have:
            continue
        try:
            text = nse.get(c["url"], LEGACY_LANDING if c["source"] == "legacy" else INTEGRATED_LANDING, json_=False)
        except RuntimeError as e:
            failed += 1
            detail.append(f"{c['period_end']}: {str(e)[:60]}")
            continue
        if text:
            _save_raw(symbol, c, text)
        p = parse_xbrl(text or "", (c.get("from_date"), c["period_end"]))
        if p is None:
            failed += 1
            detail.append(f"{c['period_end']}: not a results XBRL")
            continue
        if not dates_agree(p["period_end"], c["period_end"]):
            failed += 1
            detail.append(f"{c['period_end']}: file says {p['period_end']}")
            continue
        _store(con, symbol, c, p)
        new += 1
    status = "done" if failed == 0 else "partial"
    if not chosen:
        status = "empty"
    con.execute("INSERT OR REPLACE INTO fetch_log VALUES (?,?,?,?,?,?,?)",
                [symbol, status, len(chosen), new, failed, "; ".join(detail)[:400],
                 dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)])
    return {"symbol": symbol, "status": status, "listed": len(chosen), "new": new, "failed": failed}


# ── the research series ─────────────────────────────────────────────────────────────────────────

def quarterly(con=None, symbols=None) -> pd.DataFrame:
    """Single-quarter rows (3 months), one per (symbol, period_end), consolidated preferred."""
    own = con is None
    con = con or duckdb.connect(str(DB_PATH), read_only=True)
    q = "SELECT * FROM filings WHERE period_months = 3"
    params: list = []
    if symbols is not None:
        q += " AND symbol IN (" + ",".join(["?"] * len(symbols)) + ")"
        params = list(symbols)
    df = con.execute(q + " ORDER BY symbol, period_end", params).fetchdf()
    if own:
        con.close()
    return df


def ttm_eps(quarters: pd.DataFrame, share_events=None) -> pd.DataFrame:
    """TTM EPS per (symbol, known_date): the sum of four consecutive quarters on one basis.

    known_date = the latest broadcast among the four (the figure could not be known earlier).
    `share_events` {symbol: [(ex_date, ratio)]} (split/bonus/consolidation; corp_actions.share_events)
    restates every quarter into TODAY's share units — a quarter broadcast before a 5:1 split has its EPS
    divided by 5 — so the series pairs with a back-adjusted price. Without it EPS is as reported.
    A quarter with no EPS falls back to nothing (no guess), so the TTM is simply absent there."""
    rows = []
    for sym, g in quarters.groupby("symbol"):
        g = g.sort_values("period_end").reset_index(drop=True)
        ev = sorted((share_events or {}).get(sym, []))
        eps = []
        for _, r in g.iterrows():
            e = r["eps_basic"]
            if pd.notna(e):
                for exd, ratio in ev:
                    if pd.Timestamp(exd) > pd.Timestamp(r["broadcast_ts"]).normalize():
                        e = e / ratio
            eps.append(e)
        g["eps_adj"] = eps
        for i in range(3, len(g)):
            w = g.iloc[i - 3:i + 1]
            gaps = [(b - a).days for a, b in zip(w["period_end"], w["period_end"].iloc[1:])]
            if not all(80 <= x <= 100 for x in gaps) or w["basis"].nunique() != 1 or w["eps_adj"].isna().any():
                continue
            rows.append({"symbol": sym, "period_end": g.loc[i, "period_end"], "basis": g.loc[i, "basis"],
                         "known_date": pd.Timestamp(w["broadcast_ts"].max()).normalize(),
                         "ttm_eps": float(w["eps_adj"].sum()),
                         "ttm_np": float(w["np"].sum()) if w["np"].notna().all() else None})
    return pd.DataFrame(rows, columns=["symbol", "period_end", "basis", "known_date", "ttm_eps", "ttm_np"])


def pe_ttm_panel(close: pd.DataFrame, ttm: pd.DataFrame, max_age_days: int = 460) -> pd.DataFrame:
    """date x symbol P/E = back-adjusted close / the latest TTM EPS known on that date.

    A TTM figure older than `max_age_days` (a company that stopped filing) is dropped rather than
    carried forever; loss-makers (TTM EPS <= 0) are NaN, the same convention as the engine's `pe`."""
    out = pd.DataFrame(index=close.index, columns=close.columns, dtype=float)
    for sym, g in ttm.groupby("symbol"):
        if sym not in close.columns:
            continue
        s = g.sort_values("known_date").drop_duplicates("known_date", keep="last").set_index("known_date")["ttm_eps"]
        eps = s.reindex(s.index.union(close.index)).ffill().reindex(close.index)
        age = pd.Series(s.index, index=s.index).reindex(s.index.union(close.index)).ffill().reindex(close.index)
        eps = eps.where((close.index - pd.DatetimeIndex(age)).days <= max_age_days)
        out[sym] = close[sym] / eps.where(eps > 0)
    return out


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────

def status(con=None) -> dict:
    con = con or connect()
    n, ns = con.execute("SELECT count(*), count(DISTINCT symbol) FROM filings").fetchone()
    by = dict(con.execute("SELECT status, count(*) FROM fetch_log GROUP BY 1").fetchall())
    rng = con.execute("SELECT min(period_end), max(period_end) FROM filings").fetchone()
    return {"filings": n, "symbols": ns, "fetch_log": by, "period_range": [str(rng[0]), str(rng[1])]}


def main():
    ap = argparse.ArgumentParser(description="NSE quarterly-results XBRL -> data/nse_filings.duckdb")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--symbols-file", required=True, help="CSV with a `symbol` column")
    f.add_argument("--limit", type=int)
    f.add_argument("--throttle", type=float, default=1.0)
    f.add_argument("--redo", action="store_true", help="also revisit symbols already marked done")
    sub.add_parser("status")
    sub.add_parser("reparse")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    con = connect()
    if args.cmd == "status":
        print(status(con))
        return
    if args.cmd == "reparse":
        print(reparse(con), status(con))
        return
    rows = [r for r in csv.DictReader(open(args.symbols_file, encoding="utf-8")) if r.get("symbol")]
    alts = {r["symbol"].strip().upper(): [a.strip().upper() for a in (r.get("alts") or "").split(";") if a.strip()]
            for r in rows}
    syms = list(alts)
    done = {r[0] for r in con.execute("SELECT symbol FROM fetch_log WHERE status IN ('done','empty')").fetchall()}
    todo = [s for s in syms if args.redo or s not in done]
    if args.limit:
        todo = todo[:args.limit]
    nse = Nse(args.throttle)
    t0 = time.time()
    streak = pauses = 0
    for i, sym in enumerate(todo, 1):
        try:
            r = fetch_symbol(con, nse, sym, alts[sym])
            streak = 0
        except Exception as e:  # noqa: BLE001 — one bad symbol must not end a 20-hour run
            con.execute("INSERT OR REPLACE INTO fetch_log VALUES (?,?,?,?,?,?,?)",
                        [sym, "error", 0, 0, 0, str(e)[:300], dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)])
            r = {"symbol": sym, "status": "error"}
            streak += 1
            if streak >= 5:        # five in a row is a block or an outage, not five bad symbols
                pauses += 1
                if pauses > 3:
                    _log.error("giving up after %d pauses; re-run to resume", pauses - 1)
                    break
                _log.warning("5 consecutive errors (last: %s) - pausing 10 min", str(e)[:80])
                time.sleep(600)
                nse = Nse(args.throttle)
                streak = 0
        if i % 10 == 0 or i == len(todo):
            el = time.time() - t0
            _log.info("%d/%d %s  %.0fs elapsed, %.0fs/name, %d requests", i, len(todo), r["status"],
                      el, el / i, nse.n)
    print(status(con))


if __name__ == "__main__":
    main()
