"""Ad-hoc chat experiment 2026-07-17 (part 2): fresh 5y runs (2021-07-01 ->
2026-06-16, cold start, save=False) for every strategy in the store that has NO
saved backtest (MOM/TRD/MR families), plus fresh cold-start validation runs for
the top slice winners. Appends one JSON line per result to /tmp/gap5y_results.jsonl."""

import copy
import json
import math
import sys

sys.path.insert(0, "/mnt/storage/websites/windfall-labs/backend")
from scripts.batch_client import get_json, post_json  # noqa: E402

API = "http://127.0.0.1:8505"
START, END = "2021-07-01", "2026-06-16"
OUT = "/tmp/gap5y_results.jsonl"
VALIDATE = ["DVM_all_w_10", "DVM_all_m_10", "SZ_small_m_15", "VAL_ownpe_q_30",
            "SZ_small_w_30", "VAL_ownpe_w_10"]


def curve_points(eq):
    if isinstance(eq, dict):
        return sorted(eq.items())
    return [(p[0], p[1]) if isinstance(p, (list, tuple))
            else (p.get("date"), p.get("equity", p.get("value"))) for p in eq]


def dd_max(pts):
    peak, maxdd = None, 0.0
    for _, v in pts:
        if v is None:
            continue
        peak = v if peak is None else max(peak, v)
        maxdd = min(maxdd, v / peak - 1)
    return maxdd


def main():
    strategies = get_json(f"{API}/api/strategies")
    if isinstance(strategies, dict):
        strategies = strategies.get("strategies") or strategies.get("items")
    have_runs = {r["strategy_id"] for r in get_json(f"{API}/api/backtests")}
    todo = [s for s in strategies if (s.get("name") or s.get("id")) not in have_runs]
    names = [s.get("name") or s.get("id") for s in todo] + VALIDATE
    print(f"{len(names)} runs to do", flush=True)

    done = 0
    with open(OUT, "w") as fh:
        for nm in names:
            base = get_json(f"{API}/api/strategies/{nm}")["config"]
            cfg = copy.deepcopy(base)
            cfg["start"], cfg["end"] = START, END
            cfg["name"] = f"{nm}__5y"
            row = {"sid": nm, "kind": "validate" if nm in VALIDATE else "gapfill"}
            try:
                res = post_json(f"{API}/api/backtests", {"config": cfg, "save": False},
                                timeout=3600.0)
                s = res.get("summary", {})
                row.update(cagr=s.get("cagr"), sharpe=s.get("sharpe"),
                           maxdd=s.get("max_drawdown"),
                           maxdd_dates=s.get("max_dd_dates"))
                pts = curve_points(res.get("equity_curve") or [])
                row["n_days"] = len(pts)
            except Exception as exc:  # noqa: BLE001
                row["error"] = repr(exc)
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            done += 1
            if done % 10 == 0:
                print(f"progress {done}/{len(names)}", flush=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
