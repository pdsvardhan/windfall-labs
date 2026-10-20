"""iter-201 (item 1466, verifier round 1): do NSE's free filings carry machine-readable quarterly
profit and EPS, end to end? Fetches ONE legacy XBRL (corporates-financial-results, 2017-2024) and ONE
integrated-filing iXBRL (integrated-filing-results, 2025+) for a symbol and looks for the tags a TTM
P/E needs. Read-only; nothing stored.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from windfall.data import corp_actions as ca  # noqa: E402

SYM = sys.argv[1] if len(sys.argv) > 1 else "TCS"
TAGS = ("ProfitLossForPeriod", "ProfitLoss", "BasicEarningsLossPerShareFromContinuingOperations",
        "BasicEarningsPerShare", "DilutedEarningsLossPerShare", "RevenueFromOperations")

s = requests.Session()
s.headers.update(ca._HEADERS)


def landing(url):
    s.headers["Referer"] = url
    s.get(url, timeout=30)
    time.sleep(1.0)


def first_link(rows, keys):
    for x in rows:
        if not isinstance(x, dict):
            continue
        for k in keys:
            v = str(x.get(k) or "")
            if v.lower().startswith("http") and (".xml" in v.lower() or "xbrl" in v.lower() or ".html" in v.lower()):
                return x, v
    return None, None


def show(label, url):
    if not url:
        print(f"{label}: no machine-readable link found")
        return
    r = s.get(url, timeout=60)
    body = r.text
    found = {t: len(re.findall(rf"[:\"]{t}[\"\s>]", body)) for t in TAGS}
    print(f"{label}: http {r.status_code} {len(body):,} bytes  tags {found}")


landing("https://www.nseindia.com/companies-listing/corporate-filings-financial-results")
r = s.get("https://www.nseindia.com/api/corporates-financial-results",
          params={"index": "equities", "symbol": SYM, "period": "Quarterly"}, timeout=30)
rows = r.json() if r.status_code == 200 else []
rows = rows.get("data", []) if isinstance(rows, dict) else rows
rec, link = first_link(rows, ("xbrl",))
print("legacy filing:", {k: (rec or {}).get(k) for k in ("toDate", "filingDate", "consolidated", "audited")})
show("legacy XBRL", link)
time.sleep(1.2)

landing("https://www.nseindia.com/companies-listing/corporate-integrated-filing")
r = s.get("https://www.nseindia.com/api/integrated-filing-results",
          params={"index": "equities", "symbol": SYM}, timeout=30)
data = r.json() if r.status_code == 200 else []
rows = data.get("data", []) if isinstance(data, dict) else data
print("integrated filings:", len(rows), "first keys:", sorted(rows[0].keys())[:20] if rows else None)
rec, link = first_link(rows, ("xbrl", "ixbrl", "xbrlFile", "attachment", "xbrl_file", "ixbrlFile"))
print("integrated filing:", {k: (rec or {}).get(k) for k in list((rec or {}).keys())[:8]})
show("integrated iXBRL", link)
