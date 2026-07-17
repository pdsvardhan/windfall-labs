"""Full-protocol robustness on 5y finalists (chat experiment 2026-07-17, user-approved).
Per finalist, all fresh cold-start runs on today's data layer:
  - 5y (2021-07-01 -> 2026-06-16) with curve capture -> 10 half-year segments +
    Dec-24 correction depth/recovery
  - H1 (2021-07 -> 2024-01) and H2 (2024-01 -> 2026-06) persistence halves
  - pre-COVID out-of-window (2016-07 -> 2021-07)
  - regime overlay MA100/MA150 binary on the 5y window (top-6 only)
Results -> /tmp/robust5y_results.jsonl"""

import copy
import json
import math
import sys

sys.path.insert(0, "/mnt/storage/websites/windfall-labs/backend")
from scripts.batch_client import get_json, post_json  # noqa: E402

API = "http://127.0.0.1:8505"
OUT = "/tmp/robust5y_results.jsonl"

FINALISTS = ["DVM_all_w_10", "DVM_all_m_10", "MOM_roc252_m_10", "SZ_small_m_15",
             "SZ_small_m_20", "TRD_golden_m_10", "GRO_revg_w_10", "VAL_ownpe_q_30",
             "VAL_ownpe_w_10", "MOM_roc252_m_20", "DVM_dm_m_20"]
GATED = ["DVM_all_w_10", "DVM_all_m_10", "MOM_roc252_m_10", "SZ_small_m_15",
         "TRD_golden_m_10", "VAL_ownpe_q_30"]
WINDOWS = {"5y": ("2021-07-01", "2026-06-16"),
           "H1": ("2021-07-01", "2024-01-01"),
           "H2": ("2024-01-01", "2026-06-16"),
           "pre": ("2016-07-01", "2021-07-01")}
GATES = {"ma100": {"enabled": True, "ma_period": 100, "mode": "binary", "below_exposure": 0.0},
         "ma150": {"enabled": True, "ma_period": 150, "mode": "binary", "below_exposure": 0.0}}
SEGS = [("2021-07-01", "2022-01-01"), ("2022-01-01", "2022-07-01"),
        ("2022-07-01", "2023-01-01"), ("2023-01-01", "2023-07-01"),
        ("2023-07-01", "2024-01-01"), ("2024-01-01", "2024-07-01"),
        ("2024-07-01", "2025-01-01"), ("2025-01-01", "2025-07-01"),
        ("2025-07-01", "2026-01-01"), ("2026-01-01", "2026-06-16")]


def curve_points(eq):
    if isinstance(eq, dict):
        return sorted(eq.items())
    return [(p[0], p[1]) if isinstance(p, (list, tuple))
            else (p.get("date"), p.get("equity", p.get("value"))) for p in eq]


def seg_return(pts, a, b):
    win = [v for d, v in pts if a <= d < b and v is not None]
    return win[-1] / win[0] - 1 if len(win) > 5 else None


def correction(pts):
    """Depth + recovery through the Dec-24 -> Mar-25 correction."""
    win = [(d, v) for d, v in pts if d >= "2024-09-01" and v is not None]
    if not win:
        return None
    peak_d, peak = win[0]
    tr_d, depth = peak_d, 0.0
    rec = None
    for d, v in win:
        if d > "2025-06-30" and rec:
            break
        if v >= peak and depth == 0.0:
            peak_d, peak = d, v
        dd = v / peak - 1
        if dd < depth and d <= "2025-04-30":
            depth, tr_d = dd, d
        if depth < 0 and v >= peak:
            rec = d
            break
    return {"peak": peak_d, "trough": tr_d, "depth": depth, "recovered": rec}


def run(cfg, tag):
    try:
        res = post_json(f"{API}/api/backtests", {"config": cfg, "save": False},
                        timeout=3600.0)
    except Exception as exc:  # noqa: BLE001
        return {"tag": tag, "error": repr(exc)}
    s = res.get("summary", {})
    row = {"tag": tag, "cagr": s.get("cagr"), "sharpe": s.get("sharpe"),
           "maxdd": s.get("max_drawdown")}
    if tag.endswith("/5y"):
        pts = curve_points(res.get("equity_curve") or [])
        row["segments"] = [seg_return(pts, a, b) for a, b in SEGS]
        row["correction"] = correction(pts)
        bpts = curve_points(res.get("benchmark_curve") or [])
        if bpts:
            row["bench_segments"] = [seg_return(bpts, a, b) for a, b in SEGS]
    return row


def main():
    jobs = []
    for sid in FINALISTS:
        for wtag, (a, b) in WINDOWS.items():
            jobs.append((sid, wtag, (a, b), None))
    for sid in GATED:
        for gtag, rf in GATES.items():
            jobs.append((sid, f"5y_{gtag}", WINDOWS["5y"], rf))
    print(f"{len(jobs)} runs", flush=True)
    with open(OUT, "w") as fh:
        for i, (sid, wtag, (a, b), rf) in enumerate(jobs, 1):
            base = get_json(f"{API}/api/strategies/{sid}")["config"]
            cfg = copy.deepcopy(base)
            cfg["start"], cfg["end"] = a, b
            cfg["name"] = f"{sid}__{wtag}"
            if rf is not None:
                cfg["regime_filter"] = rf
            row = run(cfg, f"{sid}/{wtag}")
            row["sid"] = sid
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            if i % 10 == 0:
                print(f"progress {i}/{len(jobs)}", flush=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
