"""iter-201 (item 1466): is there a FREE quarterly-earnings history deep enough for a point-in-time TTM P/E?

Probes two sources for a handful of names (read-only, nothing stored):
  1. NSE's corporate financial-results filings API (same cookie pattern as corp_actions.fetch):
     how many quarterly filings, how far back, and does each carry a machine-readable XBRL link.
  2. screener.in's company page "Quarterly Results" table: how many quarters the free page shows.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from windfall.data import corp_actions as ca  # noqa: E402

SYMS = [a for a in sys.argv[1:] if not a.startswith("--")] or ["TCS", "TBZ", "KAMDHENU", "SHANTIGOLD", "INDORAMA", "VENUSREM"]
LANDING = "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"
API = "https://www.nseindia.com/api/corporates-financial-results"

s = requests.Session()
s.headers.update(ca._HEADERS)
s.headers["Referer"] = LANDING
s.get(LANDING, timeout=30)
time.sleep(1.0)

print("NSE financial-results filings (quarterly):")
for sym in SYMS:
    try:
        r = s.get(API, params={"index": "equities", "symbol": sym, "period": "Quarterly"}, timeout=30)
        rows = r.json() if r.status_code == 200 else []
    except Exception as e:  # noqa: BLE001
        print(f"  {sym:12s} error {type(e).__name__}: {e}")
        continue
    if isinstance(rows, dict):
        rows = rows.get("data") or []
    def _d(x):
        try:
            return dt.datetime.strptime(str(x.get("toDate")), "%d-%b-%Y").date()
        except (TypeError, ValueError):
            return None
    recs = [x for x in rows if isinstance(x, dict) and _d(x)]
    ends = sorted({_d(x) for x in recs})
    xb = sorted({_d(x) for x in recs if str(x.get("xbrl") or "").lower().endswith(".xml")})
    q = sorted({_d(x) for x in recs if str(x.get("cumulative") or "").lower().startswith("non")})
    print(f"  {sym:12s} http {r.status_code} filings {len(rows):4d} quarters {len(ends):3d} "
          f"{ends[:1]}..{ends[-1:]}  XBRL quarters {len(xb)} from {xb[:1]}  non-cumulative {len(q)}")
    time.sleep(1.2)

print("\nscreener.in free page, Quarterly Results columns:")
for sym in SYMS:
    r = requests.get(f"https://www.screener.in/company/{sym}/consolidated/",
                     headers={"User-Agent": "Mozilla/5.0 (Windfall personal research)"}, timeout=30)
    if r.status_code != 200:
        print(f"  {sym:12s} http {r.status_code}")
        continue
    soup = BeautifulSoup(r.text, "html.parser")
    sec = soup.find("section", id="quarters")
    cols = [th.get_text(strip=True) for th in sec.select("thead th")][1:] if sec else []
    print(f"  {sym:12s} {len(cols)} quarters: {cols[:1]}..{cols[-1:]}  "
          f"EPS row: {bool(sec and re.search('EPS', sec.get_text()))}")
    time.sleep(1.5)
