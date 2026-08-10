"""iter-147 item 934 — walk-forward the adr-041 MA100-gated configs (the #249 adoption gate).

adr-041 measured the MA100 binary index-regime gate as the first risk overlay to survive honest
measurement (DD cut 12-24pp at ~0 Sharpe cost) but recorded it as a CANDIDATE: adoption requires
the gated configs to pass the same walk-forward gate the plain strategies passed (adr-040:
3y IS / 1y OOS, metric sharpe, grid={}, robust = OOS/IS >= 0.5). This runs BOTH arms on the same
current data — the ungated baseline is re-run rather than compared against the 2026-07-17 numbers
so both arms see identical history (prices have advanced since; Trendlyne factors end 2026-07-08).

Usage: python3 docs/validation/walkforward_gated_iter147.py
  -> docs/validation/walkforward_gated_run-2026-08-10.txt
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from scripts.batch_client import get_json, post_json  # noqa: E402

API = "http://127.0.0.1:8505"
METRIC = sys.argv[1] if len(sys.argv) > 1 else "sharpe"  # item AC wants sharpe AND cagr ratios
OUT = Path(__file__).resolve().parent / f"walkforward_gated_run-2026-08-10{'' if METRIC == 'sharpe' else '_' + METRIC}.txt"

STRATS = ["DVM_user", "DVM_dm_m_20", "MOM_roc252_m_20", "CMP_valmom_m_20"]
GATE = {"enabled": True, "ma_period": 100, "mode": "binary", "below_exposure": 0.0}


def wf(config, tag):
    print(f"walk-forward {tag} ...", flush=True)
    try:
        out = post_json(f"{API}/api/walkforward",
                        {"config": config, "grid": {}, "metric": METRIC,
                         "is_years": 3.0, "oos_years": 1.0}, timeout=5400.0)
    except Exception as exc:  # noqa: BLE001
        return {"tag": tag, "error": repr(exc)}
    return {"tag": tag, "n_windows": out.get("n_windows"), "is_avg": out.get("is_avg"),
            "oos_avg": out.get("oos_avg"), "ratio": out.get("oos_to_is_ratio"),
            "degradation": out.get("degradation"), "verdict": out.get("verdict"),
            "windows": [{k: w.get(k) for k in ("is_window", "oos_window", "is_metric",
                                               "oos_metric")}
                        for w in out.get("windows", [])]}


def main():
    rows = []
    for sid in STRATS:
        base = get_json(f"{API}/api/strategies/{sid}")["config"]
        for arm, gate in (("plain", None), ("ma100_bin", GATE)):
            cfg = copy.deepcopy(base)
            if gate is not None:
                cfg["regime_filter"] = dict(gate)
            cfg["name"] = f"{sid}__{arm}"
            rows.append(wf(cfg, f"{sid}/{arm}"))

    lines = ["gated walk-forward run 2026-08-10 (iter-147 item 934, adr-041 adoption gate)",
             f"protocol: adr-040 — metric {METRIC}, 3y IS / 1y OOS, grid={{}}; robust = OOS/IS >= 0.5",
             "both arms re-run on identical current data (not compared to 2026-07-17 numbers)", ""]
    lines.append(f"{'strategy/arm':<34}{'folds':>6}{'IS avg':>9}{'OOS avg':>9}{'ratio':>7}  verdict")
    for r in rows:
        if "error" in r:
            lines.append(f"{r['tag']:<34}ERROR: {r['error'][:80]}")
            continue
        ratio = r["ratio"] if r["ratio"] is not None else float("nan")
        lines.append(f"{r['tag']:<34}{r['n_windows']:>6}{r['is_avg']:>9.3f}{r['oos_avg']:>9.3f}"
                     f"{ratio:>7.2f}  {r['verdict']}")
    report = "\n".join(lines)
    print(report)
    OUT.write_text(report + "\n\n=== per-fold detail ===\n" + json.dumps(rows, indent=1)[:150000])
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
