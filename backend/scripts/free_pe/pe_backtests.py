"""iter-201 (item 1465): Value+Momentum on the free P/E vs Trendlyne's — backtests via the live API.

The paper book's own config (CMP_valmom_m_20: tl_pe ascending + roc126 descending, top 20, monthly,
equal weight, NSE delivery costs) is run over the leaderboard windows in four variants:

  live config   tl_pe as configured — what the paper book actually does
  tl_pe req.    + entry filter `tl_pe > 0`
  free pe req.  P/E token swapped to `pe` + entry filter `pe > 0`
  momentum      roc126 alone — the control

Why the filters (verifier round 1, 2026-10-20): the blend re-weights a missing factor away, so a name
with no P/E is ranked on momentum alone. Unfiltered, 93% of the free-pe run's entries had no free P/E
— it was a momentum test. Requiring a positive P/E is the only fair comparison of the two P/Es.

Each run is repeated (identical calls differ by ~0.6pp CAGR, to-do #967); the table reports the mean
and the range. Holdings overlap (Jaccard, same rebalance day) is measured against momentum-only.
Calls POST /api/backtests with save=false (nothing is stored).

iter-206 (#969) knobs: EXCLUDE_FIN=1 drops banks/NBFCs from every arm (the screener.in store cannot
see them), TABLE=<name> picks the result table, REPEATS=<n> the repeats per cell.
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
REPEATS = int(os.environ.get("REPEATS", "2"))
EXCLUDE_FIN = os.environ.get("EXCLUDE_FIN", "0") == "1"      # iter-206 (#969): banks/NBFCs out of every arm
FIN_SECTORS = ["bank", "financ"]                              # substring match, lower-cased, on the sector label
TABLE = os.environ.get("TABLE", "pe_backtests")               # result table; the iter-201 one is kept as is


def call(path, body=None):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.load(r)


def holdings(trades) -> dict:
    """{entry date: set(tickers held right after that rebalance)}"""
    t = pd.DataFrame(trades)
    if t.empty:
        return {}
    t["entry_date"] = pd.to_datetime(t["entry_date"])
    t["exit_date"] = pd.to_datetime(t["exit_date"])
    out = {}
    for d in sorted(t["entry_date"].unique()):
        held = t[(t["entry_date"] <= d) & ((t["exit_date"].isna()) | (t["exit_date"] > d))]
        out[pd.Timestamp(d)] = set(held["ticker"])
    return out


def jaccard(a: dict, b: dict) -> float:
    common = sorted(set(a) & set(b))
    ov = [len(a[d] & b[d]) / max(len(a[d] | b[d]), 1) for d in common]
    return sum(ov) / max(len(ov), 1)


def variants(base: dict) -> dict:
    def swap(cfg, tok):
        cfg["rank_blend"] = [{**f, "factor": tok} if f["factor"] == "tl_pe" else f
                             for f in cfg["rank_blend"]]
        cfg["rank_by"] = tok
        return cfg

    live = copy.deepcopy(base)
    tl_req = copy.deepcopy(base)
    tl_req["entry_filters"] = list(tl_req.get("entry_filters") or []) + ["tl_pe > 0"]
    pe_req = swap(copy.deepcopy(base), "pe")
    pe_req["entry_filters"] = list(pe_req.get("entry_filters") or []) + ["pe > 0"]
    mom = copy.deepcopy(base)
    mom["rank_blend"] = [f for f in mom["rank_blend"] if f["factor"] != "tl_pe"]
    mom["rank_by"] = "roc126"
    out = {"live config": live, "tl_pe req.": tl_req, "free pe req.": pe_req, "momentum": mom}
    if EXCLUDE_FIN:
        # iter-206 (#969): the screener.in store excludes banks/NBFCs by design, so the free P/E can never
        # see them; take them out of EVERY arm (matched by substring on the sector label) so the two
        # P/Es are compared on the same companies.
        for cfg in out.values():
            cfg["universe"]["exclude_sectors"] = list(cfg["universe"].get("exclude_sectors") or []) + FIN_SECTORS
    return out


def main() -> None:
    base = call("/api/strategies/CMP_valmom_m_20")["config"]
    rows = []
    for wname, (start, end) in WINDOWS.items():
        runs = {}
        for label, cfg0 in variants(base).items():
            stats, trades = [], None
            for rep in range(REPEATS):
                cfg = copy.deepcopy(cfg0)
                cfg["start"], cfg["end"] = start, end
                cfg["name"] = f"CMP_valmom_m_20 [{label}] {wname} #{rep}"
                res = call("/api/backtests", {"config": cfg, "save": False})
                s = res.get("summary") or {}
                stats.append((s.get("cagr") or 0, s.get("sharpe") or 0, s.get("max_drawdown") or 0,
                              len(res.get("trades") or [])))
                trades = trades if trades is not None else (res.get("trades") or [])
            runs[label] = holdings(trades)
            df = pd.DataFrame(stats, columns=["cagr", "sharpe", "maxdd", "trades"])
            rows.append({"window": wname, "variant": label, "runs": len(df),
                         "cagr": df.cagr.mean(), "cagr_min": df.cagr.min(), "cagr_max": df.cagr.max(),
                         "sharpe": df.sharpe.mean(), "maxdd": df.maxdd.mean(),
                         "trades": df.trades.mean()})
            r = rows[-1]
            print(f"{wname:14s} {label:13s} CAGR {r['cagr']:+.1%} ({r['cagr_min']:+.1%}..{r['cagr_max']:+.1%})"
                  f"  Sharpe {r['sharpe']:.2f}  MaxDD {r['maxdd']:+.1%}  trades {r['trades']:.0f}", flush=True)
        for r in rows:
            if r["window"] == wname:
                r["overlap_vs_momentum"] = jaccard(runs[r["variant"]], runs["momentum"])
        print(f"{'':14s} overlap with momentum-only: " + ", ".join(
            f"{r['variant']} {r['overlap_vs_momentum']:.0%}" for r in rows if r["window"] == wname)
              + f"; free pe req. vs tl_pe req. {jaccard(runs['free pe req.'], runs['tl_pe req.']):.0%}",
              flush=True)
    df = pd.DataFrame(rows)
    con = duckdb.connect(str(OUT))
    con.register("df", df)
    con.execute(f"CREATE OR REPLACE TABLE {TABLE} AS SELECT * FROM df")
    con.close()


if __name__ == "__main__":
    main()
