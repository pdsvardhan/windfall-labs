"""iter-201 (item 1467): can the screener.in store refresh on a server schedule? Measured on a sample.

Runs the production ingester (same code path, --cross-check like the original runs) for a random
sample of the store's tickers against a COPY of the store, then reports: wall time per name, failures,
and what changed versus the live store (new fiscal periods, revised values, confidence changes).

Usage: WINDFALL_DATA_DIR=<scratch dir holding a copy of screener_fundamentals.duckdb> \
       python -I screener_refresh_sample.py <live screener_fundamentals.duckdb> [n] [seed]
Never point WINDFALL_DATA_DIR at the live data dir: the ingester writes to the store it finds there.
"""
from __future__ import annotations

import os
import random
import sys
import time
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from windfall.data import screener_fundamentals as sf  # noqa: E402

live_path = Path(sys.argv[1])
n = int(sys.argv[2]) if len(sys.argv) > 2 else 40
seed = int(sys.argv[3]) if len(sys.argv) > 3 else 201
assert Path(os.environ["WINDFALL_DATA_DIR"]).resolve() != live_path.parent.resolve(), \
    "WINDFALL_DATA_DIR must be a scratch copy, not the live data dir"

live = duckdb.connect(str(live_path), read_only=True)
tickers = [r[0] for r in live.execute(
    "SELECT DISTINCT ticker FROM fundamentals_history "
    "WHERE confidence NOT IN ('excluded-financial') ORDER BY 1").fetchall()]
random.Random(seed).shuffle(tickers)
sample = sorted(tickers[:n])


def snap(con, t):
    rows = con.execute("SELECT period_end, eps, net_profit, revenue, confidence FROM fundamentals_history "
                       "WHERE ticker = ? ORDER BY period_end", [t]).fetchall()
    return {str(r[0]): r[1:] for r in rows}


before = {t: snap(live, t) for t in sample}
live.close()

t0 = time.time()
out = sf.ingest([(t.replace(".NS", ""), None) for t in sample], cross_check=True)
secs = time.time() - t0

after_con = duckdb.connect(str(sf.DB_PATH), read_only=True)
after = {t: snap(after_con, t) for t in sample}
after_con.close()

new_periods, revised, conf_changed, lost = {}, {}, {}, {}
for t in sample:
    b, a = before[t], after[t]
    added = sorted(set(a) - set(b))
    gone = sorted(set(b) - set(a))
    if added:
        new_periods[t] = added
    if gone:
        lost[t] = gone
    rv = [p for p in set(a) & set(b)
          if any(x is not None and y is not None and abs((x - y) / (abs(y) or 1)) > 0.01
                 for x, y in zip(a[p][:3], b[p][:3]))]
    if rv:
        revised[t] = sorted(rv)
    cb = {v[3] for v in b.values()}
    ca = {v[3] for v in a.values()}
    if cb != ca:
        conf_changed[t] = (sorted(cb), sorted(ca))

print(f"sample {len(sample)} names, wall {secs:.0f}s ({secs / max(len(sample), 1):.1f}s per name)")
print("ingest counts:", out["counts"])
fails = [r for r in out["results"] if r["status"] == "failed"]
print("failed:", [(r["symbol"], r.get("reason")) for r in fails])
print(f"names gaining fiscal periods: {len(new_periods)}  -> {dict(list(new_periods.items())[:12])}")
print(f"names losing periods: {len(lost)} -> {dict(list(lost.items())[:8])}")
print(f"names with a revised value (>1% on eps/np/revenue): {len(revised)} -> "
      f"{dict(list(revised.items())[:8])}")
print(f"confidence changed: {conf_changed}")
latest = sorted({max(a) for a in after.values() if a})
print("latest fiscal period per name after refresh (distinct):", latest[-6:])
