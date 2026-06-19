"""Historical fundamentals from screener.in -> standalone point-in-time store.

Implements the six handling rules locked in ADR-013 (triangulation-validated):
  1. symbol -> slug via the screener search API (cached); never assume symbol == slug
  2. financials (banks/NBFCs) excluded from the fundamental-DVM
  3. Net Profit normalized to owner-attributable (minority-adjusted via yfinance overlap)
  4. per-share metrics taken split-adjusted
  5. periods keyed on the actual fiscal period-end date (non-March / FY-change safe)
  6. ratios (ROE/ROCE/OPM/NPM/D-E) COMPUTED from raw lines, not scraped

Plus a per-stock self-check (Layer-1 accounting identities + optional yfinance cross-vote)
that QUARANTINES a stock rather than silently ingesting a bad parse.

ONE DOOR (adr-018): writes a standalone DB (data/screener_fundamentals.duckdb); never opens
windfall.duckdb. The symbol list is passed in, so the engine's DB is never touched here.

Run:  python -m windfall.data.screener_fundamentals --symbols COFORGE,ASHOKLEY --cross-check
      python -m windfall.data.screener_fundamentals --symbols-file syms.csv
      python -m windfall.data.screener_fundamentals --status
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import time
from urllib.parse import quote, unquote

import duckdb
import requests
from bs4 import BeautifulSoup

from ..config import DATA_DIR

UA = "Mozilla/5.0 (Windfall personal research; contact pdsvardhan7@gmail.com)"
DB_PATH = DATA_DIR / "screener_fundamentals.duckdb"
CACHE = DATA_DIR / "cache" / "screener"
FETCH_SLEEP = 1.2

MONTHS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
          "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
_MONTH_END = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
              7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}

SCHEMA = """
CREATE TABLE IF NOT EXISTS fundamentals_history (
    ticker VARCHAR NOT NULL, period_end DATE NOT NULL, basis VARCHAR NOT NULL,
    source VARCHAR DEFAULT 'screener', is_financial BOOLEAN,
    revenue DOUBLE, op_profit DOUBLE, interest DOUBLE, depreciation DOUBLE,
    pbt DOUBLE, tax DOUBLE, net_profit DOUBLE, net_profit_owner DOUBLE, eps DOUBLE,
    total_assets DOUBLE, equity DOUBLE, borrowings DOUBLE, cfo DOUBLE,
    opm DOUBLE, npm DOUBLE, roe DOUBLE, roce DOUBLE, de DOUBLE, np_yoy DOUBLE,
    confidence VARCHAR, flags VARCHAR, fetched_at TIMESTAMP,
    PRIMARY KEY (ticker, period_end, basis)
);
CREATE TABLE IF NOT EXISTS slug_map (
    symbol VARCHAR PRIMARY KEY, slug VARCHAR, screener_name VARCHAR, resolved_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ingest_log (
    run_at TIMESTAMP, requested INTEGER, ingested INTEGER,
    quarantined INTEGER, excluded INTEGER, failed INTEGER
);
"""


# ---------- parse helpers ----------
def _num(s):
    if s is None:
        return None
    s = str(s).strip().replace(",", "").replace("%", "").replace("₹", "").strip()
    if s in ("", "-", "NA", "N/A", "nan", "[object Object]"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _period_end(label: str):
    """'Mar 2024' / 'Dec 2023' -> date(2024,3,31). Returns None for non-period labels (TTM)."""
    parts = label.replace("-", " ").split()
    if len(parts) < 2 or parts[0] not in MONTHS or not parts[-1].isdigit():
        return None
    mo, yr = MONTHS[parts[0]], int(parts[-1])
    day = 29 if (mo == 2 and yr % 4 == 0) else _MONTH_END[mo]
    return dt.date(yr, mo, day)


def connect(db_path=DB_PATH):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute(SCHEMA)
    return con


# ---------- screener fetch + parse ----------
def resolve_slug(symbol: str, name: str | None = None, con=None) -> str | None:
    """Resolve NSE symbol -> screener slug via the search API; cache in slug_map."""
    if con is not None:
        row = con.execute("SELECT slug FROM slug_map WHERE symbol = ?", [symbol]).fetchone()
        if row:
            return row[0]
    q = name or symbol
    url = "https://www.screener.in/api/company/search/?q=" + quote(q)
    arr = None
    for attempt in range(3):  # the search API rate-limits bursts; back off + retry
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
            if r.status_code == 200:
                arr = r.json()
                break
            if r.status_code not in (429, 503):
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2.0 * (attempt + 1))
    time.sleep(FETCH_SLEEP)  # politeness between search calls
    if not arr:
        return None
    cand = [a for a in arr if "DVR" not in a.get("name", "")] or arr
    slug = cand[0]["url"].strip("/").split("/")[1]
    if con is not None:
        con.execute("INSERT OR REPLACE INTO slug_map VALUES (?,?,?,?)",
                    [symbol, slug, cand[0].get("name"), dt.datetime.now(dt.timezone.utc)])
    return slug


def fetch_html(slug: str, basis: str = "consolidated") -> tuple[str, int]:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{slug}_{basis}.html"
    if path.exists() and (time.time() - path.stat().st_mtime) < 86400:
        return path.read_text(encoding="utf-8"), 200
    sub = "consolidated/" if basis == "consolidated" else ""
    r = requests.get(f"https://www.screener.in/company/{slug}/{sub}",
                     headers={"User-Agent": UA}, timeout=30)
    if r.status_code == 200:
        path.write_text(r.text, encoding="utf-8")
    time.sleep(FETCH_SLEEP)
    return r.text, r.status_code


def parse_company(html: str) -> dict:
    """-> {section_id: {row_label: {period_label: float}}}, with section 'shareholding' kept."""
    soup = BeautifulSoup(html, "lxml")
    out = {}
    m = re.search(r"nseindia\.com[^\"']*symbol=([A-Z0-9&%-]+)", html)
    out["_nse"] = unquote(m.group(1)) if m else None  # decode %26 -> & (e.g. ARE&M)
    for sec in soup.find_all("section"):
        sid = sec.get("id") or ""
        table = sec.find("table", class_="data-table")
        if not table or not table.find("thead"):
            continue
        years = [th.get_text(" ", strip=True)
                 for th in table.find("thead").find_all("th")][1:]
        rows = {}
        for tr in table.find("tbody").find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue
            rows[cells[0].get_text(" ", strip=True).rstrip(" +")] = dict(
                zip(years, [_num(c.get_text(" ", strip=True)) for c in cells[1:]]))
        out[sid] = rows
    return out


# ---------- normalize ----------
def is_financial(parsed: dict) -> bool:
    pl = parsed.get("profit-loss", {})
    return "Sales" not in pl or "Operating Profit" not in pl


def _owner_np_factor(group_np: dict, yf_ni: dict) -> float:
    """Median(owner / group) over overlapping years; 1.0 if no usable overlap."""
    ratios = []
    for y, g in group_np.items():
        if g and y in yf_ni and yf_ni[y] is not None and g != 0:
            ratios.append(yf_ni[y] / g)
    if not ratios:
        return 1.0
    ratios.sort()
    f = ratios[len(ratios) // 2]
    return f if 0.3 < f < 1.05 else 1.0  # guard against bad overlap


def build_records(ticker: str, parsed: dict, basis: str, yf_ni: dict | None = None) -> list[dict]:
    """One record per fiscal period-end with raw lines + computed ratios."""
    pl = parsed.get("profit-loss", {})
    bs = parsed.get("balance-sheet", {})
    cf = parsed.get("cash-flow", {})
    fin = is_financial(parsed)

    sales = pl.get("Sales", {})
    # group NP by year for the minority factor
    np_row = pl.get("Net Profit", {})
    group_by_year = {}
    for lbl, v in np_row.items():
        pe = _period_end(lbl)
        if pe:
            group_by_year[pe.year] = v
    factor = _owner_np_factor(group_by_year, yf_ni) if (yf_ni and not fin) else 1.0

    recs = []
    prev_owner = None
    for lbl in sorted(sales or np_row, key=lambda x: (_period_end(x) or dt.date.min)):
        pe = _period_end(lbl)
        if pe is None:
            continue

        def g(sec, row):
            return sec.get(row, {}).get(lbl)

        rev = g(pl, "Sales")
        op = g(pl, "Operating Profit")
        interest = g(pl, "Interest")
        depr = g(pl, "Depreciation")
        pbt = g(pl, "Profit before tax")
        net = g(pl, "Net Profit")
        eps = g(pl, "EPS in Rs")
        assets = g(bs, "Total Assets")
        equity = None
        if "Equity Capital" in bs:
            equity = (bs["Equity Capital"].get(lbl) or 0) + (bs.get("Reserves", {}).get(lbl) or 0)
        borrow = g(bs, "Borrowings")
        cfo = g(cf, "Cash from Operating Activity")

        # owner-NP: use yfinance's exact owner figure where it overlaps; factor only to extrapolate
        if yf_ni and pe.year in yf_ni and yf_ni[pe.year] is not None:
            owner = yf_ni[pe.year]
        elif net is not None:
            owner = net * factor
        else:
            owner = None
        tax_amt = (pbt - net) if (pbt is not None and net is not None) else None  # absolute tax (₹Cr)
        ebit = (pbt + interest) if (pbt is not None and interest is not None) else None
        opm = (op / rev * 100) if (op is not None and rev) else None
        npm = (owner / rev * 100) if (owner is not None and rev) else None
        roe = (owner / equity * 100) if (owner is not None and equity) else None
        roce = (ebit / (equity + (borrow or 0)) * 100) if (ebit is not None and equity) else None
        de = (borrow / equity) if (borrow is not None and equity) else None
        np_yoy = ((owner - prev_owner) / abs(prev_owner) * 100) \
            if (owner is not None and prev_owner not in (None, 0)) else None
        prev_owner = owner if owner is not None else prev_owner

        recs.append({
            "ticker": ticker, "period_end": pe, "basis": basis, "source": "screener",
            "is_financial": fin, "revenue": rev, "op_profit": op, "interest": interest,
            "depreciation": depr, "pbt": pbt, "tax": tax_amt, "net_profit": net,
            "net_profit_owner": owner, "eps": eps, "total_assets": assets, "equity": equity,
            "borrowings": borrow, "cfo": cfo, "opm": opm, "npm": npm, "roe": roe,
            "roce": roce, "de": de, "np_yoy": np_yoy,
        })
    return recs


def self_check(parsed: dict, recs: list[dict], yf=None) -> tuple[str, list[str]]:
    """Layer-1 identities + optional yfinance cross-vote -> (confidence, flags)."""
    flags = []
    if is_financial(parsed):
        return "excluded-financial", ["FIN-SCHEMA"]
    pl = parsed.get("profit-loss", {})
    # identity OP == Sales - Expenses
    sales, exp, op = pl.get("Sales", {}), pl.get("Expenses", {}), pl.get("Operating Profit", {})
    idn = idok = 0
    for y in sales:
        s, e, o = sales.get(y), exp.get(y), op.get(y)
        if None not in (s, e, o):
            idn += 1
            if e and abs(o - (s - e)) / max(abs(s - e), 1) <= 0.015:
                idok += 1
    identity_rate = idok / idn if idn else 1.0
    if identity_rate < 0.8:
        flags.append(f"identity-{idok}/{idn}")

    # yfinance cross-vote on Revenue + Total Assets — a SOFT corroboration only.
    # yfinance's India data is itself unreliable (e.g. INFY revenue comes back ~85x wrong), and
    # revenue definitions legitimately differ (gross-vs-net of levies). So a yf disagreement marks
    # the stock 'low' for review — never a hard quarantine. Wrong-COMPANY mappings are caught
    # deterministically by the NSE-symbol guard in ingest_symbol, not here.
    if yf is not None:
        rev_by_yr = {r["period_end"].year: r["revenue"] for r in recs if r["revenue"]}
        as_by_yr = {r["period_end"].year: r["total_assets"] for r in recs if r["total_assets"]}
        for label, scr in (("rev", rev_by_yr), ("assets", as_by_yr)):
            ext = yf.get(label, {})
            n = ok = 0
            for y, v in scr.items():
                if y in ext and ext[y]:
                    n += 1
                    ok += abs(v - ext[y]) / abs(ext[y]) <= 0.05
            if n and ok < n - 1:
                flags.append(f"yf-{label}-{ok}/{n}")

    if identity_rate < 0.5:  # the only hard self-check signal (a genuinely broken parse)
        return "quarantined", flags
    if identity_rate < 0.8 or flags:
        return "low", flags
    return "high", flags


# ---------- yfinance third source ----------
def yf_overlap(yf_ticker: str) -> dict:
    """{'ni': {yr:val}, 'rev': {yr:val}, 'assets': {yr:val}} in INR Cr. Best-effort."""
    try:
        import yfinance as yf
        tk = yf.Ticker(yf_ticker)

        def series(df, *keys):
            if df is None or df.empty:
                return {}
            for k in keys:
                if k in df.index:
                    return {c.year: (None if v != v else float(v) / 1e7)
                            for c, v in zip(df.columns, df.loc[k].values)}
            return {}
        return {
            "ni": series(tk.income_stmt, "Net Income", "Net Income Common Stockholders"),
            "rev": series(tk.income_stmt, "Total Revenue", "Operating Revenue"),
            "assets": series(tk.balance_sheet, "Total Assets"),
        }
    except Exception:  # noqa: BLE001
        return {}


# ---------- ingest ----------
def _try_fetch(slug: str, basis: str):
    """Fetch consolidated, fall back to standalone. -> (html, code, basis)."""
    html, code = fetch_html(slug, basis)
    if code != 200 and basis == "consolidated":
        h2, c2 = fetch_html(slug, "standalone")
        if c2 == 200:
            return h2, c2, "standalone"
    return html, code, basis


def _load(slug: str, basis: str, ticker: str, yf_ni):
    """Fetch -> parse -> build records. -> (parsed, recs, basis, code)."""
    html, code, basis = _try_fetch(slug, basis)
    if code != 200:
        return None, [], basis, code
    parsed = parse_company(html)
    if "profit-loss" not in parsed:
        return parsed, [], basis, code
    return parsed, build_records(ticker, parsed, basis, yf_ni=yf_ni), basis, code


def ingest_symbol(con, symbol: str, name: str | None, basis: str, cross_check: bool,
                  sector: str | None = None) -> dict:
    ticker = f"{symbol}.NS"
    # Sector pre-filter: financials are excluded from the fundamental-DVM (ADR-013 rule 2),
    # so skip the fetch entirely rather than scrape + quarantine them.
    if sector and "financ" in sector.lower():
        return {"symbol": symbol, "status": "excluded", "confidence": "excluded-financial",
                "periods": 0, "flags": ["SECTOR-FINANCIAL"], "slug": symbol}

    # Direct page first: slug == NSE symbol for ~all stocks, so the rate-limited search API
    # is only needed when the direct symbol 404s (renamed/demerged tickers, e.g. TATAMOTORS->TMCV).
    row = con.execute("SELECT slug FROM slug_map WHERE symbol = ?", [symbol]).fetchone()
    slug = row[0] if row else symbol
    yf = yf_overlap(ticker) if cross_check else None
    yf_ni = (yf or {}).get("ni")

    parsed, recs, basis, code = _load(slug, "consolidated", ticker, yf_ni)
    if code != 200:
        slug2 = resolve_slug(symbol, name, con)  # polite search-API fallback
        if slug2 and slug2 != slug:
            slug = slug2
            parsed, recs, basis, code = _load(slug, "consolidated", ticker, yf_ni)
    if code != 200:
        return {"symbol": symbol, "status": "failed", "reason": f"http-{code}", "slug": slug}
    # consolidated page exists but is empty (standalone-only MNCs, e.g. ABBOTINDIA/ABB) -> standalone
    if not recs and basis == "consolidated":
        parsed, recs, basis, _ = _load(slug, "standalone", ticker, yf_ni)
    if not recs:
        return {"symbol": symbol, "status": "failed", "reason": "empty-parse", "slug": slug}

    confidence, flags = self_check(parsed, recs, yf)
    # mapping guard: the resolved page must be the company we asked for
    nse = parsed.get("_nse")
    if nse and nse.upper() != symbol.upper():
        confidence = "quarantined"
        flags = [f"MAP-MISMATCH(page={nse})"] + flags
    else:
        con.execute("INSERT OR REPLACE INTO slug_map VALUES (?,?,?,?)",
                    [symbol, slug, nse, dt.datetime.now(dt.timezone.utc)])
    fnow = dt.datetime.now(dt.timezone.utc)
    fl = ",".join(flags) or None

    con.execute("DELETE FROM fundamentals_history WHERE ticker = ? AND basis = ?", [ticker, basis])
    cols = ["ticker", "period_end", "basis", "source", "is_financial", "revenue", "op_profit",
            "interest", "depreciation", "pbt", "tax", "net_profit", "net_profit_owner", "eps",
            "total_assets", "equity", "borrowings", "cfo", "opm", "npm", "roe", "roce", "de",
            "np_yoy", "confidence", "flags", "fetched_at"]
    for r in recs:
        r.update({"confidence": confidence, "flags": fl, "fetched_at": fnow})
        con.execute(f"INSERT OR REPLACE INTO fundamentals_history ({','.join(cols)}) "
                    f"VALUES ({','.join('?' * len(cols))})", [r.get(c) for c in cols])
    return {"symbol": symbol, "slug": slug, "basis": basis, "periods": len(recs),
            "confidence": confidence, "status": "excluded" if confidence.startswith("excluded")
            else ("quarantined" if confidence == "quarantined" else "ok"), "flags": flags}


def ingest(symbols: list[tuple[str, str | None]], basis="consolidated", cross_check=False) -> dict:
    con = connect()
    counts = {"ok": 0, "low": 0, "quarantined": 0, "excluded": 0, "failed": 0}
    results = []
    for entry in symbols:
        symbol = entry[0]
        name = entry[1] if len(entry) > 1 else None
        sector = entry[2] if len(entry) > 2 else None
        try:
            res = ingest_symbol(con, symbol, name, basis, cross_check, sector)
        except Exception as e:  # noqa: BLE001
            res = {"symbol": symbol, "status": "failed", "reason": f"{type(e).__name__}: {e}"}
        st = res.get("confidence", res["status"])
        if res["status"] == "ok" and res.get("confidence") == "low":
            counts["low"] += 1
        else:
            counts[res["status"] if res["status"] in counts else "failed"] += 1
        results.append(res)
    con.execute("INSERT INTO ingest_log VALUES (?,?,?,?,?,?)",
                [dt.datetime.now(dt.timezone.utc), len(symbols), counts["ok"] + counts["low"],
                 counts["quarantined"], counts["excluded"], counts["failed"]])
    con.close()
    return {"requested": len(symbols), "counts": counts, "results": results}


def status() -> dict:
    con = connect()
    n = con.execute("SELECT COUNT(*) FROM fundamentals_history").fetchone()[0]
    nt = con.execute("SELECT COUNT(DISTINCT ticker) FROM fundamentals_history").fetchone()[0]
    byc = dict(con.execute(
        "SELECT confidence, COUNT(DISTINCT ticker) FROM fundamentals_history GROUP BY 1").fetchall())
    rng = con.execute("SELECT MIN(period_end), MAX(period_end) FROM fundamentals_history").fetchone()
    con.close()
    return {"rows": n, "tickers": nt, "by_confidence": byc,
            "period_range": [str(rng[0]), str(rng[1])]}


def main():
    ap = argparse.ArgumentParser(description="screener.in historical fundamentals ingester")
    ap.add_argument("--symbols", help="comma-separated NSE symbols")
    ap.add_argument("--symbols-file", help="CSV with columns symbol[,name[,sector]]")
    ap.add_argument("--basis", default="consolidated", choices=["consolidated", "standalone"])
    ap.add_argument("--cross-check", action="store_true", help="yfinance cross-vote per stock")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    if args.status:
        print(status())
        return
    syms = []
    if args.symbols:
        syms = [(s.strip().upper(), None) for s in args.symbols.split(",") if s.strip()]
    elif args.symbols_file:
        import csv
        for row in csv.reader(open(args.symbols_file, encoding="utf-8")):
            if row and row[0] and row[0].strip().lower() != "symbol":
                syms.append((row[0].strip().upper(),
                             row[1].strip() if len(row) > 1 else None,
                             row[2].strip() if len(row) > 2 else None))
    if not syms:
        ap.error("need --symbols, --symbols-file, or --status")

    out = ingest(syms, basis=args.basis, cross_check=args.cross_check)
    print(f"requested {out['requested']}  counts {out['counts']}")
    for r in out["results"]:
        line = f"  {r['symbol']:<12} {r.get('status'):<11}"
        if "periods" in r:
            line += f" {r['periods']:>2}p conf={r.get('confidence')} slug={r.get('slug')}"
        if r.get("flags"):
            line += f" flags={','.join(r['flags'])}"
        if r.get("reason"):
            line += f" reason={r['reason']}"
        print(line)


if __name__ == "__main__":
    main()
