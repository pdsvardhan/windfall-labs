"""iter-23 item 635 — regime-overlay drawdown study on the 4 paper strategies (the #103 blocker).

All four paper strategies draw down 55-75%; stops were measured useless (adr-039); own-equity
factor-timing was measured harmful (adr-033/034). The one built-in lever never measured on the
deployables is the INDEX-based regime_filter (benchmark vs its own MA — a market-direction gate,
not the self-referential equity gate adr-033 rejected). This measures it honestly, with costs.

Variants per strategy (regime_filter is resolve-affecting: warmup pad — so each variant is a
full direct /api/backtests run; the batch endpoint rightly refuses regime grids since #219):
  off              baseline (as deployed)
  ma200_bin        binary: 100% -> 0% exposure when benchmark < its 200dma
  ma200_half       binary but de-risk to 50% below the MA (below_exposure 0.5)
  ma100_bin        faster gate, full de-risk
  ma200_scale      mode=scale, below_exposure 0.5

Verdict rule (stated up front, honest): a variant "earns adoption consideration" only if it cuts
MaxDD by >= 10pp at a Sharpe cost <= 0.10 — same bar adr-039 applied to stops. Otherwise the
finding is recorded and the overlay stays off.

Usage: python3 docs/validation/regime_study_iter23.py  → docs/validation/regime_study_run-2026-07-17.txt
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from scripts.batch_client import get_json, post_json  # noqa: E402

API = "http://127.0.0.1:8505"
OUT = Path(__file__).resolve().parent / "regime_study_run-2026-07-17.txt"

STRATS = ["DVM_user", "DVM_dm_m_20", "MOM_roc252_m_20", "CMP_valmom_m_20"]
VARIANTS = {
    "off":         None,
    "ma200_bin":   {"enabled": True, "ma_period": 200, "mode": "binary", "below_exposure": 0.0},
    "ma200_half":  {"enabled": True, "ma_period": 200, "mode": "binary", "below_exposure": 0.5},
    "ma100_bin":   {"enabled": True, "ma_period": 100, "mode": "binary", "below_exposure": 0.0},
    "ma200_scale": {"enabled": True, "ma_period": 200, "mode": "scale", "below_exposure": 0.5},
}


def run(cfg, tag):
    print(f"running {tag} ...", flush=True)
    try:
        res = post_json(f"{API}/api/backtests", {"config": cfg, "save": False}, timeout=3600.0)
    except Exception as exc:  # noqa: BLE001
        return {"tag": tag, "error": repr(exc)}
    s = res.get("summary", {})
    return {"tag": tag,
            **{k: s.get(k) for k in ("cagr", "sharpe", "max_drawdown", "calmar", "exposure",
                                     "annual_turnover")},
            "warnings": [w for w in res.get("warnings", []) if "regime" in w or "benchmark" in w][:3]}


def main():
    all_rows = {}
    for sid in STRATS:
        base = get_json(f"{API}/api/strategies/{sid}")["config"]
        rows = []
        for vtag, rf in VARIANTS.items():
            cfg = copy.deepcopy(base)
            if rf is not None:
                cfg["regime_filter"] = rf
            cfg["name"] = f"{sid}__{vtag}"
            rows.append(run(cfg, f"{sid}/{vtag}"))
        all_rows[sid] = rows

    lines = ["regime-overlay study 2026-07-17 (iter-23 item 635)",
             "adoption bar: MaxDD cut >= 10pp at Sharpe cost <= 0.10 vs off", ""]
    for sid, rows in all_rows.items():
        lines.append(sid)
        base = next((r for r in rows if r["tag"].endswith("/off") and "error" not in r), None)
        lines.append(f"  {'variant':<14}{'cagr':>8}{'sharpe':>8}{'maxdd':>8}{'calmar':>8}"
                     f"{'expo':>6}  vs-off")
        for r in rows:
            if "error" in r:
                lines.append(f"  {r['tag'].split('/')[1]:<14}ERROR: {r['error'][:70]}")
                continue
            v = r["tag"].split("/")[1]
            note = ""
            if base and v != "off":
                dd_cut = (base["max_drawdown"] - r["max_drawdown"]) * -100  # pp of DD removed
                sh_cost = base["sharpe"] - r["sharpe"]
                note = f"dd{dd_cut:+.1f}pp sh{-sh_cost:+.2f}"
                if dd_cut >= 10 and sh_cost <= 0.10:
                    note += "  << CLEARS BAR"
            lines.append(f"  {v:<14}{r['cagr']:>8.3f}{r['sharpe']:>8.2f}{r['max_drawdown']:>8.3f}"
                         f"{(r.get('calmar') or 0):>8.2f}{(r.get('exposure') or 0):>6.2f}  {note}")
        lines.append("")
    report = "\n".join(lines)
    print(report)
    OUT.write_text(report + "\n\n=== raw ===\n" + json.dumps(all_rows, indent=1)[:150000])
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
