"""iter-23 item 634 — blend parity pass: reproduce the adr-035 70/30 headline from saved sleeves.

adr-035 (2026-06-26) advertises 70/30 MOM/LV: CAGR 29.5% / Sharpe 1.27 / MaxDD -42.7%
(plain MOM bar: 38.7% / 1.26 / -49.5%). iter-20 and iter-21 both flagged that this does NOT
reproduce from the saved sleeves (observed 22.9-28.4% / 1.09-1.24). This harness pins down why.

Known discrepancies to test:
- adr-035 says the LV sleeve ranks `atr14/close`; every stored LV sleeve ranks `atr20/close`.
- Stored sleeves pin end=2026-06-16 (the ADR window), so window drift is NOT the cause on a
  stored-sleeve run; the data layer under the window HAS changed (audit F1-F6 + the iter-22
  merged refresh).
- Holdings: the ADR bar sleeve is n=10; iter-20 tried 10/20 variants.

Runs (all POST /api/rotation, monthly, default 20bps switch cost, capital Rs10L per adr-034):
  A  [1.0] MOM_roc252_m_10                        expect ~38.7 / 1.26 / -49.5
  B  [0.7,0.3] MOM_roc252_m_10 + LV_atr_m_10      expect ~29.5 / 1.27 / -42.7  (the headline)
  C  [0.6,0.4] MOM_roc252_m_10 + LV_atr_m_10      expect ~26.4 / 1.27 / -40.4
  D  [0.7,0.3] MOM_roc252_m_20 + LV_atr_m_20      iter-20's variant (22.9-28.4 band)
  E  [0.7,0.3] MOM_m_10 + LV(atr14/close, m_10)   the sleeve as adr-035 DESCRIBES it
  F  [1.0] LV_atr_m_10                            expect ~7.6 CAGR / 0.68 / -29.7 (adr-035 LV)
Usage: python3 docs/validation/blend_parity_iter23.py   (api must be up; writes
       docs/validation/blend_parity_run-2026-07-17.txt)
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from scripts.batch_client import get_json, post_json  # noqa: E402

API = "http://127.0.0.1:8505"
OUT = Path(__file__).resolve().parent / "blend_parity_run-2026-07-17.txt"


def cfg_of(sid: str) -> dict:
    return get_json(f"{API}/api/strategies/{sid}")["config"]


def rotation(name, sleeves, weights, capital=1_000_000.0):
    out = post_json(f"{API}/api/rotation",
                    {"sleeves": sleeves, "weights": weights, "rebalance": "monthly",
                     "capital": capital, "benchmark": "NIFTY500", "name": name},
                    timeout=3600.0)
    s = out.get("summary", out)
    row = {k: s.get(k) for k in ("cagr", "sharpe", "max_drawdown", "calmar",
                                 "annual_turnover", "exposure")}
    row["name"] = name
    return row, out


def main():
    mom10, mom20 = cfg_of("MOM_roc252_m_10"), cfg_of("MOM_roc252_m_20")
    lv10, lv20 = cfg_of("LV_atr_m_10"), cfg_of("LV_atr_m_20")
    lv10_atr14 = copy.deepcopy(lv10)
    lv10_atr14["rank_by"] = "atr14 / close"
    lv10_atr14["name"] = "LV_atr14_m_10_adhoc"

    expects = {
        "A_MOM_bar": (0.387, 1.26, -0.495),
        "B_70_30_stored": (0.295, 1.27, -0.427),
        "C_60_40_stored": (0.264, 1.27, -0.404),
        "D_70_30_n20": (None, None, None),
        "E_70_30_atr14": (0.295, 1.27, -0.427),
        "F_LV_alone": (0.076, 0.68, -0.297),
    }
    runs = [
        ("A_MOM_bar", [mom10], [1.0]),
        ("B_70_30_stored", [mom10, lv10], [0.7, 0.3]),
        ("C_60_40_stored", [mom10, lv10], [0.6, 0.4]),
        ("D_70_30_n20", [mom20, lv20], [0.7, 0.3]),
        ("E_70_30_atr14", [mom10, lv10_atr14], [0.7, 0.3]),
        ("F_LV_alone", [lv10], [1.0]),
    ]
    rows, raw = [], {}
    for name, sleeves, weights in runs:
        print(f"running {name} ...", flush=True)
        try:
            row, full = rotation(name, sleeves, weights)
        except Exception as exc:  # noqa: BLE001
            row, full = {"name": name, "error": repr(exc)}, {"error": repr(exc)}
        rows.append(row)
        raw[name] = {k: v for k, v in full.items() if k not in
                     ("equity_curve", "benchmark_curve", "drawdown_curve", "trades")}

    lines = ["blend parity run 2026-07-17 (iter-23 item 634)", ""]
    lines.append(f"{'run':<18}{'cagr':>8}{'sharpe':>8}{'maxdd':>8}{'calmar':>8}{'turn':>8}"
                 f"   expected(cagr/sharpe/dd)")
    for r in rows:
        e = expects.get(r["name"], (None,) * 3)
        if "error" in r:
            lines.append(f"{r['name']:<18}ERROR: {r['error'][:90]}")
            continue
        lines.append(f"{r['name']:<18}{r['cagr']:>8.3f}{r['sharpe']:>8.2f}"
                     f"{r['max_drawdown']:>8.3f}{(r.get('calmar') or 0):>8.2f}"
                     f"{(r.get('annual_turnover') or 0):>8.2f}   "
                     f"{e[0]}/{e[1]}/{e[2]}")
    report = "\n".join(lines)
    print(report)
    OUT.write_text(report + "\n\n=== raw (curves stripped) ===\n"
                   + json.dumps(raw, indent=1, default=str)[:200000])
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
