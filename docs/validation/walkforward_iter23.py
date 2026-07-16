"""iter-23 item 633 — formal walk-forward on the 5 deployed paper strategies (the adr-006 gate).

adr-006 + the locked must_have say: "no strategy is approved for live signals until a walk-forward
shows acceptable in-sample vs out-of-sample degradation." None of the strategies now paper-trading
has recorded IS/OOS evidence — this harness closes that gap.

Design:
- grid={} per strategy: the deployed configs are LOCKED (no parameter fitting happens live), so
  the honest gate question is "does the fixed config's edge persist out-of-sample across rolling
  folds?" — walk_forward with an empty grid measures exactly that (IS metric vs OOS metric, same
  config, rolling 3y/1y windows). verdict: robust = OOS/IS >= 0.5 on Sharpe.
- One gridded run for the momentum flagship (n_holdings 10/15/20/25) to test whether IS-chosen
  holdings hold OOS (parameter-choice overfit check).
- Bonus untouched-OOS decade: MOM_roc252 on 2007-01-01..2016-06-10 — price data exists from 2006
  and NO strategy decision was ever fitted on that decade (2008 bear included). One direct run.

Usage: python3 docs/validation/walkforward_iter23.py  → docs/validation/walkforward_run-2026-07-17.txt
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from scripts.batch_client import get_json, post_json  # noqa: E402

API = "http://127.0.0.1:8505"
OUT = Path(__file__).resolve().parent / "walkforward_run-2026-07-17.txt"

STRATS = ["DVM_user", "DVM_dm_m_20", "MOM_roc252_m_20", "CMP_valmom_m_20", "LV_atr_m_10"]


def wf(config, grid, tag):
    print(f"walk-forward {tag} ...", flush=True)
    try:
        out = post_json(f"{API}/api/walkforward",
                        {"config": config, "grid": grid, "metric": "sharpe",
                         "is_years": 3.0, "oos_years": 1.0}, timeout=5400.0)
    except Exception as exc:  # noqa: BLE001
        return {"tag": tag, "error": repr(exc)}
    return {"tag": tag, "n_windows": out.get("n_windows"), "is_avg": out.get("is_avg"),
            "oos_avg": out.get("oos_avg"), "ratio": out.get("oos_to_is_ratio"),
            "degradation": out.get("degradation"), "verdict": out.get("verdict"),
            "windows": [{k: w.get(k) for k in ("is_window", "oos_window", "best_overrides",
                                               "is_metric", "oos_metric")}
                        for w in out.get("windows", [])]}


def main():
    rows = []
    for sid in STRATS:
        cfg = get_json(f"{API}/api/strategies/{sid}")["config"]
        rows.append(wf(cfg, {}, sid))
    mom = get_json(f"{API}/api/strategies/MOM_roc252_m_10")["config"]
    rows.append(wf(mom, {"n_holdings": [10, 15, 20, 25]}, "MOM_roc252_gridded_nholdings"))

    # untouched-OOS decade (2008 bear in-sample for nobody)
    print("pre-2016 OOS decade run ...", flush=True)
    dec = dict(mom, start="2007-01-01", end="2016-06-10", name="MOM_roc252_oos_2007_2016")
    try:
        res = post_json(f"{API}/api/backtests", {"config": dec, "save": False}, timeout=3600.0)
        s = res.get("summary", {})
        decade = {k: s.get(k) for k in ("cagr", "sharpe", "max_drawdown", "calmar", "exposure")}
        decade["warnings"] = res.get("warnings", [])[:6]
    except Exception as exc:  # noqa: BLE001
        decade = {"error": repr(exc)}

    lines = ["walk-forward run 2026-07-17 (iter-23 item 633) — metric: sharpe, 3y IS / 1y OOS", ""]
    lines.append(f"{'strategy':<30}{'folds':>6}{'IS avg':>9}{'OOS avg':>9}{'ratio':>7}  verdict")
    for r in rows:
        if "error" in r:
            lines.append(f"{r['tag']:<30}ERROR: {r['error'][:80]}")
            continue
        lines.append(f"{r['tag']:<30}{r['n_windows']:>6}{r['is_avg']:>9.3f}{r['oos_avg']:>9.3f}"
                     f"{(r['ratio'] if r['ratio'] is not None else float('nan')):>7.2f}  {r['verdict']}")
    lines.append("")
    lines.append("untouched OOS decade — MOM_roc252 m10 2007-01-01..2016-06-10 (includes 2008):")
    lines.append("  " + json.dumps(decade, default=str)[:400])
    report = "\n".join(lines)
    print(report)
    OUT.write_text(report + "\n\n=== per-fold detail ===\n" + json.dumps(rows, indent=1)[:150000])
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
