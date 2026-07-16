"""iter-23 follow-ups: (a) solo-sleeve baselines the rotation endpoint 400'd on (single-sleeve
weights=[1.0] edge case) — run as direct backtests instead; (b) ma150_bin period-robustness point
for the regime finding (100 beat 200; is the response monotonic in between, or is 100 a lucky
period?). Appends to the two existing run files."""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from scripts.batch_client import get_json, post_json  # noqa: E402

API = "http://127.0.0.1:8505"
V = Path(__file__).resolve().parent


def run(cfg, tag):
    print(f"running {tag} ...", flush=True)
    try:
        res = post_json(f"{API}/api/backtests", {"config": cfg, "save": False}, timeout=3600.0)
    except Exception as exc:  # noqa: BLE001
        return {"tag": tag, "error": repr(exc)}
    s = res.get("summary", {})
    return {"tag": tag, **{k: s.get(k) for k in ("cagr", "sharpe", "max_drawdown", "calmar",
                                                 "exposure", "annual_turnover")}}


out = []
for sid, tag in [("MOM_roc252_m_10", "A_MOM_bar_direct"), ("LV_atr_m_10", "F_LV_alone_direct")]:
    cfg = get_json(f"{API}/api/strategies/{sid}")["config"]
    out.append(run(cfg, tag))

for sid in ["DVM_user", "DVM_dm_m_20", "MOM_roc252_m_20", "CMP_valmom_m_20"]:
    base = get_json(f"{API}/api/strategies/{sid}")["config"]
    cfg = copy.deepcopy(base)
    cfg["regime_filter"] = {"enabled": True, "ma_period": 150, "mode": "binary",
                            "below_exposure": 0.0}
    cfg["name"] = f"{sid}__ma150_bin"
    out.append(run(cfg, f"{sid}/ma150_bin"))

report = "\n".join(
    f"{r['tag']:<32}" + (f"ERROR {r['error'][:60]}" if "error" in r else
                         f"cagr={r['cagr']:.3f} sharpe={r['sharpe']:.2f} "
                         f"maxdd={r['max_drawdown']:.3f} expo={r.get('exposure') or 0:.2f}")
    for r in out)
print(report)
(V / "followup_run-2026-07-17.txt").write_text(report + "\n\n" + json.dumps(out, indent=1))
with open(V / "blend_parity_run-2026-07-17.txt", "a") as f:
    f.write("\n\n=== follow-up (direct backtests; rotation endpoint 400s on single-sleeve) ===\n"
            + report.split("\n")[0] + "\n" + report.split("\n")[1] + "\n")
with open(V / "regime_study_run-2026-07-17.txt", "a") as f:
    f.write("\n\n=== follow-up: ma150_bin period-robustness ===\n"
            + "\n".join(report.split("\n")[2:]) + "\n")
print("wrote followup_run-2026-07-17.txt + appended to parity/regime files")
