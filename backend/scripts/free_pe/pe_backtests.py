"""iter-201 (item 1465): Value+Momentum on the free P/E vs Trendlyne's — backtests via the live API.

The paper book's own config (CMP_valmom_m_20: tl_pe ascending + roc126 descending, top 20, monthly,
equal weight, NSE delivery costs) is run unchanged except for the P/E token, over the leaderboard
windows. Holdings overlap is measured rebalance by rebalance from each run's trades.

Calls POST /api/backtests on :8505 with save=false (nothing is stored). ~1 min per run.
"""
from __future__ import annotations

import copy
import json
import os
import urllib.request
from pathlib import Path

import duckdb
import pandas as pd

API = "http://127.0.0.1:8505"
OUT = Path(os.environ["WINDFALL_DATA_DIR"]) / "free_pe.duckdb"
WINDOWS = {"overall 10y": ("2016-06-10", "2026-06-16"),
           "post-COVID 5y": ("2021-07-01", "2026-06-16"),
           "pre-COVID": ("2016-07-01", "2021-07-01")}


def call(path, body=None):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.load(r)


def holdings(trades) -> dict:
    """{entry date: set(tickers held right after that rebalance)}"""
    t = pd.DataFrame(trades)
    t["entry_date"] = pd.to_datetime(t["entry_date"])
    t["exit_date"] = pd.to_datetime(t["exit_date"])
    out = {}
    for d in sorted(t["entry_date"].unique()):
        held = t[(t["entry_date"] <= d) & ((t["exit_date"].isna()) | (t["exit_date"] > d))]
        out[pd.Timestamp(d)] = set(held["ticker"])
    return out


def main() -> None:
    base = call("/api/strategies/CMP_valmom_m_20")["config"]
    rows, runs = [], {}
    for wname, (start, end) in WINDOWS.items():
        for label, tok in (("Trendlyne tl_pe", "tl_pe"), ("free pe", "pe")):
            cfg = copy.deepcopy(base)
            cfg["start"], cfg["end"] = start, end
            cfg["rank_blend"] = [{**f, "factor": tok} if f["factor"] == "tl_pe" else f
                                 for f in cfg["rank_blend"]]
            cfg["rank_by"] = tok
            cfg["name"] = f"CMP_valmom_m_20 [{tok}] {wname}"
            res = call("/api/backtests", {"config": cfg, "save": False})
            s = res.get("summary") or {}
            runs[(wname, tok)] = res.get("trades") or []
            rows.append({"window": wname, "pe": label, "cagr": s.get("cagr"), "sharpe": s.get("sharpe"),
                         "maxdd": s.get("max_drawdown"), "turnover": s.get("turnover"),
                         "trades": len(res.get("trades") or []),
                         "bench_cagr": s.get("benchmark_cagr")})
            print(f"{wname:14s} {label:16s} CAGR {s.get('cagr', 0):+.1%}  Sharpe {s.get('sharpe', 0):.2f}  "
                  f"MaxDD {s.get('max_drawdown', 0):+.1%}  trades {len(res.get('trades') or [])}  "
                  f"warnings {len(res.get('warnings') or [])}", flush=True)
        a, b = holdings(runs[(wname, "tl_pe")]), holdings(runs[(wname, "pe")])
        common = sorted(set(a) & set(b))
        ov = [len(a[d] & b[d]) / max(len(a[d] | b[d]), 1) for d in common]
        print(f"{'':14s} same-day holdings overlap (Jaccard) at {len(common)} common rebalances: "
              f"mean {sum(ov) / max(len(ov), 1):.0%}", flush=True)
        rows[-1]["overlap"] = rows[-2]["overlap"] = sum(ov) / max(len(ov), 1)
    df = pd.DataFrame(rows)
    con = duckdb.connect(str(OUT))
    con.register("df", df)
    con.execute("CREATE OR REPLACE TABLE pe_backtests AS SELECT * FROM df")
    con.close()


if __name__ == "__main__":
    main()
