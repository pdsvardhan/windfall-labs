"""Index universe resolution.

Primary source is NSE's published constituent CSV (symbol + ISIN + sector). If that fetch fails
(common from a server IP), we fall back to a bundled list of large, liquid NSE names so the
pipeline always has *something* to work with. Coverage is always reported honestly downstream.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass

import requests

from ..config import UNIVERSE_DIR, ensure_dirs

NSE_INDEX_CSV = {
    "nifty50": "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
    "nifty100": "https://archives.nseindia.com/content/indices/ind_nifty100list.csv",
    "nifty200": "https://archives.nseindia.com/content/indices/ind_nifty200list.csv",
    "nifty500": "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
    "niftymidcap150": "https://archives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
    "niftysmallcap250": "https://archives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
    "niftymicrocap250": "https://archives.nseindia.com/content/indices/ind_niftymicrocap250_list.csv",
    "niftytotalmarket": "https://archives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv",
}
# Alias: "nifty750" == the Total Market index (~750 names: Nifty 500 + Midcap/Smallcap/Microcap).
NSE_INDEX_CSV["nifty750"] = NSE_INDEX_CSV["niftytotalmarket"]

# Full NSE mainboard equity list (~1800 EQ-series names) — the broadest investable universe.
NSE_EQUITY_LIST_CSV = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

# Yahoo Finance symbols for the index series themselves (benchmarks).
BENCHMARK_YF = {
    "NIFTY50": "^NSEI",
    "NIFTY500": "^CRSLDX",
    "NIFTY100": "^CNX100",
    "NIFTY200": "^CNX200",
    "NIFTYMIDCAP": "^NSEMDCP50",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/csv,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

# A conservative fallback of liquid large/mid-cap NSE symbols (no ".NS" suffix here).
FALLBACK_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "HINDUNILVR", "ITC", "SBIN",
    "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK", "BAJFINANCE", "ASIANPAINT", "MARUTI",
    "HCLTECH", "SUNPHARMA", "TITAN", "ULTRACEMCO", "WIPRO", "NESTLEIND", "ONGC", "NTPC",
    "POWERGRID", "TATAMOTORS", "TATASTEEL", "JSWSTEEL", "ADANIENT", "ADANIPORTS", "COALINDIA",
    "BAJAJFINSV", "GRASIM", "HINDALCO", "DRREDDY", "CIPLA", "DIVISLAB", "BRITANNIA", "EICHERMOT",
    "HEROMOTOCO", "BPCL", "IOC", "INDUSINDBK", "TECHM", "APOLLOHOSP", "TATACONSUM", "SBILIFE",
    "HDFCLIFE", "BAJAJ-AUTO", "M&M", "SHREECEM", "PIDILITIND", "DABUR", "GODREJCP", "MARICO",
    "HAVELLS", "DLF", "SIEMENS", "ABB", "BANKBARODA", "PNB", "CANBK", "GAIL", "VEDL",
    "AMBUJACEM", "ACC", "LUPIN", "AUROPHARMA", "BIOCON", "TORNTPHARM", "MUTHOOTFIN", "CHOLAFIN",
    "PEL", "BERGEPAINT", "COLPAL", "PGHH", "UBL", "MCDOWELL-N", "PAGEIND", "BOSCHLTD", "MOTHERSON",
    "BALKRISIND", "MRF", "TVSMOTOR", "ASHOKLEY", "TATAPOWER", "ADANIGREEN", "ADANIPOWER",
    "INDIGO", "NAUKRI", "PERSISTENT", "LTIM", "COFORGE", "MPHASIS", "OFSS", "TRENT", "DMART",
    "PIIND", "SRF", "DEEPAKNTR", "AARTIIND", "UPL", "ZYDUSLIFE", "ALKEM", "GLENMARK", "IPCALAB",
]


@dataclass
class UniverseMember:
    symbol: str           # NSE symbol, e.g. "RELIANCE"
    ticker: str           # yfinance ticker, e.g. "RELIANCE.NS"
    name: str | None = None
    sector: str | None = None
    isin: str | None = None


def to_ticker(symbol: str) -> str:
    return f"{symbol.strip().upper()}.NS"


def _fetch_nse_csv(url: str) -> list[UniverseMember]:
    resp = requests.get(url, headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    members: list[UniverseMember] = []
    for r in rows:
        sym = (r.get("Symbol") or r.get("symbol") or "").strip()
        if not sym:
            continue
        members.append(
            UniverseMember(
                symbol=sym,
                ticker=to_ticker(sym),
                name=(r.get("Company Name") or r.get("Company") or "").strip() or None,
                sector=(r.get("Industry") or r.get("Sector") or "").strip() or None,
                isin=(r.get("ISIN Code") or r.get("ISIN") or "").strip() or None,
            )
        )
    return members


def _fetch_equity_list() -> list[UniverseMember]:
    """Fetch the full NSE mainboard equity list (EQUITY_L.csv), keeping only EQ-series names."""
    resp = requests.get(NSE_EQUITY_LIST_CSV, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    members: list[UniverseMember] = []
    for r in rows:
        # EQUITY_L columns are space-padded; normalize keys.
        rr = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()}
        series = (rr.get("SERIES") or rr.get(" SERIES") or "").strip()
        sym = (rr.get("SYMBOL") or "").strip()
        if not sym or (series and series != "EQ"):
            continue
        members.append(UniverseMember(
            symbol=sym, ticker=to_ticker(sym),
            name=(rr.get("NAME OF COMPANY") or "").strip() or None,
            isin=(rr.get("ISIN NUMBER") or "").strip() or None,
        ))
    return members


def get_universe(index: str = "nifty500", use_cache: bool = True) -> list[UniverseMember]:
    """Resolve an index to its constituents. Caches the CSV under data/universe/.

    `index` may be any key in NSE_INDEX_CSV (e.g. nifty500, niftytotalmarket/nifty750) or
    'allnse' for the full mainboard equity list.
    """
    ensure_dirs()
    index = index.lower()
    cache_path = UNIVERSE_DIR / f"{index}.csv"

    if use_cache and cache_path.exists():
        with cache_path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        if rows:
            return [
                UniverseMember(
                    symbol=r["symbol"], ticker=r["ticker"],
                    name=r.get("name") or None, sector=r.get("sector") or None,
                    isin=r.get("isin") or None,
                )
                for r in rows
            ]

    members: list[UniverseMember] = []
    try:
        if index in ("allnse", "nse", "equity"):
            members = _fetch_equity_list()
        elif index in NSE_INDEX_CSV:
            members = _fetch_nse_csv(NSE_INDEX_CSV[index])
    except Exception as exc:  # noqa: BLE001 — fall back, never hard-fail universe resolution
        print(f"[universe] NSE fetch failed for {index}: {exc!r}; using fallback list.")

    if not members:
        members = [UniverseMember(symbol=s, ticker=to_ticker(s)) for s in FALLBACK_SYMBOLS]

    # Persist resolved membership for reproducibility.
    with cache_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["symbol", "ticker", "name", "sector", "isin"])
        w.writeheader()
        for m in members:
            w.writerow({"symbol": m.symbol, "ticker": m.ticker, "name": m.name or "",
                        "sector": m.sector or "", "isin": m.isin or ""})
    return members


def benchmark_ticker(name: str) -> str:
    """Map a benchmark name (e.g. NIFTY500) to a yfinance index symbol."""
    return BENCHMARK_YF.get(name.upper().replace(" ", ""), "^CRSLDX")
