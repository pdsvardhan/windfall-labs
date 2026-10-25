"""iter-206 (#970): download a few NSE filings per symbol to disk so the parser can be built against
real files. Usage: python nse_samples.py <outdir> SYM [SYM ...]   (writes <outdir>/<SYM>/{legacy,integrated}_*.{xml,html}
plus listing_*.json)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from windfall.data import corp_actions as ca  # noqa: E402

out = Path(sys.argv[1])
syms = sys.argv[2:]
s = requests.Session()
s.headers.update(ca._HEADERS)


def landing(url):
    s.headers["Referer"] = url
    s.get(url, timeout=30)
    time.sleep(1.0)


landing("https://www.nseindia.com/companies-listing/corporate-filings-financial-results")
for sym in syms:
    d = out / sym
    d.mkdir(parents=True, exist_ok=True)
    r = s.get("https://www.nseindia.com/api/corporates-financial-results",
              params={"index": "equities", "symbol": sym, "period": "Quarterly"}, timeout=30)
    rows = r.json() if r.status_code == 200 else []
    rows = rows.get("data", []) if isinstance(rows, dict) else rows
    (d / "listing_legacy.json").write_text(json.dumps(rows, indent=1))
    print(sym, "legacy listing", r.status_code, len(rows), "keys", sorted(rows[0].keys()) if rows else None)
    got = 0
    for row in rows:
        u = str(row.get("xbrl") or "")
        if u.lower().endswith(".xml") and got < 3 and (got == 0 or row is rows[len(rows) // 2] or row is rows[-1]):
            b = s.get(u, timeout=60)
            (d / f"legacy_{row.get('toDate')}.xml").write_bytes(b.content)
            print("   ", row.get("toDate"), row.get("filingDate"), u[-60:], b.status_code, len(b.content))
            got += 1
            time.sleep(1.0)
    time.sleep(1.0)

landing("https://www.nseindia.com/companies-listing/corporate-integrated-filing")
for sym in syms:
    d = out / sym
    r = s.get("https://www.nseindia.com/api/integrated-filing-results",
              params={"index": "equities", "symbol": sym}, timeout=30)
    data = r.json() if r.status_code == 200 else []
    rows = data.get("data", []) if isinstance(data, dict) else data
    (d / "listing_integrated.json").write_text(json.dumps(rows, indent=1))
    print(sym, "integrated listing", r.status_code, len(rows), "keys", sorted(rows[0].keys()) if rows else None)
    for row in rows[:2]:
        for k, v in row.items():
            if isinstance(v, str) and v.lower().startswith("http") and ("xbrl" in k.lower() or "xml" in v.lower() or "html" in v.lower()):
                b = s.get(v, timeout=60)
                (d / f"integrated_{row.get('qe_Date') or row.get('toDate') or 'x'}_{k}.xml").write_bytes(b.content)
                print("   ", k, v[-70:], b.status_code, len(b.content))
                time.sleep(1.0)
                break
    time.sleep(1.0)
