"""Curate backend/data/leaderboards.json — the persisted dataset behind /leaderboards.

Sources (all already persisted):
  - stored backtest runs via the live API (overall 10y board)
  - docs/validation/postcovid5y_combined_run-2026-07-17.json (post-COVID 5y board + families)
  - docs/validation/postcovid5y_robustness_run-2026-07-17.jsonl (pre-COVID board + verdicts)

Rerunnable any time; the site endpoint just serves the JSON this writes. Verdict labels are
the owner-reviewed conclusions of the 2026-07-17 study (docs/validation/postcovid5y_study_*.md).
"""
from __future__ import annotations

import json
import math
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = os.environ.get("WINDFALL_API", "http://127.0.0.1:8505")
ROOT = Path(__file__).resolve().parents[2]
VAL = ROOT / "docs" / "validation"
OUT = ROOT / "backend" / "data" / "leaderboards.json"

COMBINED = VAL / "postcovid5y_combined_run-2026-07-17.json"
ROBUST = VAL / "postcovid5y_robustness_run-2026-07-17.jsonl"

FAMILY_META = {
    "DVM": "Trendlyne D/V/M scores (all-3 or durability+momentum)",
    "MOM": "Pure price momentum (6/12-month returns, relative strength)",
    "TRD": "Trend-following (golden cross, near 52-week high)",
    "CMP": "Composites (quality+value+momentum blends)",
    "QUA": "Quality (ROE, low debt, margins)",
    "VAL": "Value (own-history P/E and P/BV percentiles)",
    "GRO": "Growth (revenue / net-profit growth)",
    "LV": "Low volatility (defensive sleeve of the 70/30 blend)",
    "MR": "Mean reversion (buy pullbacks / RSI dips)",
    "SZ": "Small caps",
}

# Owner-reviewed verdicts from the 2026-07-17 robustness protocol.
VERDICTS = {
    "DVM_all_w_10": ("survivor", "Zero losing half-years in 5y; also 43% pre-COVID"),
    "MOM_roc252_m_10": ("survivor", "Strong in both eras; 8/10 halves beat benchmark"),
    "DVM_all_m_10": ("survivor", "Consistent across every window; monthly cadence"),
    "SZ_small_m_15": ("regime-bet", "H1 50% -> H2 13%; pre-COVID just 6% — post-COVID artifact"),
    "SZ_small_m_20": ("regime-bet", "Same fade as SZ_small_m_15"),
    "VAL_ownpe_q_30": ("regime-bet", "Shallow drawdowns but pre-COVID 9.8%; edge is post-2021 only"),
    "VAL_ownpe_w_10": ("noise", "H1 53% -> H2 2.2%; one hot stretch carried the number"),
    "TRD_golden_m_10": ("noise", "Lone 38% in a family whose median is 14%; worst DD of finalists"),
    "MOM_roc252_m_20": ("incumbent", "Paper book; solid but n=10 variant leads this window"),
    "DVM_dm_m_20": ("incumbent-flag", "H2 only 4.3% — recent 2.5y is weak; matches live paper lag"),
}


def get(path: str):
    with urllib.request.urlopen(f"{API}{path}") as r:
        return json.load(r)


def curve_points(eq):
    if isinstance(eq, dict):
        return sorted(eq.items())
    return [(p[0], p[1]) if isinstance(p, (list, tuple))
            else (p.get("date"), p.get("equity", p.get("value"))) for p in eq]


def curve_metrics(pts, start=None, end=None):
    pts = [(d, v) for d, v in pts if v is not None
           and (start is None or d >= start) and (end is None or d < end)]
    if len(pts) < 60:
        return None
    vals = [v for _, v in pts]
    yrs = len(vals) / 252.0
    cagr = (vals[-1] / vals[0]) ** (1 / yrs) - 1
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    sharpe = mean / math.sqrt(var) * math.sqrt(252) if var > 0 else 0.0
    peak, maxdd = vals[0], 0.0
    for v in vals:
        peak = max(peak, v)
        maxdd = min(maxdd, v / peak - 1)
    return {"cagr": round(cagr, 4), "sharpe": round(sharpe, 3), "maxdd": round(maxdd, 4)}


def fam(sid: str) -> str:
    return sid.split("_")[0]


def main():
    # ── overall 10y board (latest stored run per strategy) ──
    latest: dict[str, dict] = {}
    for r in get("/api/backtests"):
        sid = r["strategy_id"]
        if sid not in latest or r["created_at"] > latest[sid]["created_at"]:
            latest[sid] = r
    overall = []
    for sid, r in latest.items():
        s = r.get("summary") or {}
        if s.get("cagr") is None:
            continue
        overall.append({"sid": sid, "family": fam(sid), "cagr": s["cagr"],
                        "sharpe": s.get("sharpe"), "maxdd": s.get("max_drawdown"),
                        "maxdd_dates": s.get("max_dd_dates")})
    overall.sort(key=lambda x: -(x["cagr"] or 0))

    # benchmark metrics (full window + pre-COVID slice) from any stored curve
    bench_full = bench_pre = None
    for r in latest.values():
        try:
            full = get(f"/api/backtests/{r['id']}")
        except Exception:  # noqa: BLE001
            continue
        bpts = curve_points(full.get("benchmark_curve") or [])
        if bpts:
            bench_full = curve_metrics(bpts)
            bench_pre = curve_metrics(bpts, start="2016-07-01", end="2021-07-01")
            break

    # ── post-COVID 5y board ──
    combined = json.loads(COMBINED.read_text())
    postcovid = sorted(
        ({"sid": m["sid"], "family": fam(m["sid"]), "cagr": m["cagr"], "sharpe": m["sharpe"],
          "maxdd": m["maxdd"], "src": m["src"]} for m in combined),
        key=lambda x: -x["cagr"])

    # ── robustness rows -> pre-COVID board + verdicts board ──
    rob: dict[str, dict[str, dict]] = {}
    for line in ROBUST.read_text().splitlines():
        row = json.loads(line)
        rob.setdefault(row["sid"], {})[row["tag"].split("/", 1)[1]] = row
    precovid, verdicts = [], []
    for sid, w in rob.items():
        pre, f5, h1, h2 = w.get("pre", {}), w.get("5y", {}), w.get("H1", {}), w.get("H2", {})
        if pre.get("cagr") is not None:
            precovid.append({"sid": sid, "family": fam(sid), "cagr": pre["cagr"],
                             "sharpe": pre["sharpe"], "maxdd": pre["maxdd"]})
        segs = f5.get("segments") or []
        bsegs = f5.get("bench_segments") or []
        beat = sum(1 for s, b in zip(segs, bsegs)
                   if s is not None and b is not None and s > b)
        v, note = VERDICTS.get(sid, ("finalist", ""))
        verdicts.append({"sid": sid, "family": fam(sid), "verdict": v, "note": note,
                         "cagr_5y": f5.get("cagr"), "sharpe_5y": f5.get("sharpe"),
                         "maxdd_5y": f5.get("maxdd"), "h1_cagr": h1.get("cagr"),
                         "h2_cagr": h2.get("cagr"), "pre_cagr": pre.get("cagr"),
                         "pre_sharpe": pre.get("sharpe"), "seg_beat": beat,
                         "seg_total": len([s for s in segs if s is not None])})
    precovid.sort(key=lambda x: -x["cagr"])
    order = {"survivor": 0, "incumbent": 1, "incumbent-flag": 2, "regime-bet": 3,
             "noise": 4, "finalist": 5}
    verdicts.sort(key=lambda x: (order.get(x["verdict"], 9), -(x["cagr_5y"] or 0)))

    # ── family medians (post-COVID window) ──
    fams: dict[str, list[float]] = {}
    for m in combined:
        fams.setdefault(fam(m["sid"]), []).append(m["cagr"])
    families = []
    for f, cs in fams.items():
        cs.sort()
        families.append({"family": f, "desc": FAMILY_META.get(f, ""),
                         "median_cagr": cs[len(cs) // 2], "best_cagr": cs[-1], "n": len(cs)})
    families.sort(key=lambda x: -x["median_cagr"])

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "boards": {
            "overall": {
                "title": "Overall (10 years)",
                "window": "2016-06-10 → 2026-06-16",
                "caption": "Every stored sweep run, full window, net of costs, survivorship-free. "
                           "High CAGR with a deep MaxDD is not a free lunch — sort by Sharpe too.",
                "benchmark": bench_full, "rows": overall},
            "postcovid": {
                "title": "Post-COVID (5 years)",
                "window": "2021-07-01 → 2026-06-16",
                "caption": "All 289 configs on the last five years. 'slice' rows are warm-start "
                           "slices of stored curves and read ~4-8pp CAGR high; 'fresh' rows are "
                           "cold-start re-runs on the current data layer.",
                "benchmark": {"cagr": 0.112, "sharpe": 0.81, "maxdd": -0.188}, "rows": postcovid},
            "precovid": {
                "title": "Pre-COVID check (2016-21)",
                "window": "2016-07-01 → 2021-07-01",
                "caption": "The out-of-window test for the 5y finalists: did the edge also exist "
                           "before COVID? Includes the 2018-19 bear and the COVID crash.",
                "benchmark": bench_pre, "rows": precovid},
            "families": {
                "title": "Families (post-COVID)",
                "window": "2021-07-01 → 2026-06-16",
                "caption": "Median beats cherry-picked best: a family whose median is strong has "
                           "a real edge; a lone hot config in a weak family is usually luck.",
                "rows": families},
            "verdicts": {
                "title": "Robustness verdicts",
                "window": "protocol run 2026-07-17",
                "caption": "Full-protocol result per finalist: 5y fresh, half-split persistence "
                           "(H1 2021-23 vs H2 2024-26), pre-COVID out-of-window, and half-year "
                           "segments vs benchmark. Survivor = passed everything.",
                "rows": verdicts},
        },
    }
    OUT.write_text(json.dumps(data, indent=1))
    print(f"wrote {OUT} — boards:",
          {k: len(v["rows"]) for k, v in data["boards"].items()})


if __name__ == "__main__":
    main()
