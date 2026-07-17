"""Ad-hoc chat experiment 2026-07-17: re-score all stored sweep backtests on the
post-COVID window (2021-07-01 onward) by slicing their stored equity curves.
Warm-start slice, not a cold re-run — fine for ranking; finalists get fresh runs."""

import json
import math
import sys

sys.path.insert(0, "/mnt/storage/websites/windfall-labs/backend")
from scripts.batch_client import get_json  # noqa: E402

API = "http://127.0.0.1:8505"
START = "2021-07-01"


def curve_points(eq):
    if isinstance(eq, dict):
        return sorted(eq.items())
    pts = []
    for p in eq:
        if isinstance(p, (list, tuple)):
            pts.append((p[0], p[1]))
        else:
            pts.append((p.get("date"), p.get("equity", p.get("value"))))
    return pts


def metrics(pts):
    pts = [(d, v) for d, v in pts if d >= START and v is not None]
    if len(pts) < 100:
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
    return {"cagr": cagr, "sharpe": sharpe, "maxdd": maxdd,
            "start": pts[0][0], "end": pts[-1][0]}


def main():
    runs = get_json(f"{API}/api/backtests")
    latest = {}
    for r in runs:
        sid = r["strategy_id"]
        if sid not in latest or r["created_at"] > latest[sid]["created_at"]:
            latest[sid] = r
    rows, bench = [], None
    for i, (sid, r) in enumerate(sorted(latest.items())):
        try:
            full = get_json(f"{API}/api/backtests/{r['id']}")
        except Exception as exc:  # noqa: BLE001
            print(f"SKIP {sid}: {exc!r}", file=sys.stderr)
            continue
        m = metrics(curve_points(full.get("equity_curve") or []))
        if m is None:
            continue
        m["sid"] = sid
        m["full_cagr"] = (full.get("summary") or {}).get("cagr")
        rows.append(m)
        if bench is None and full.get("benchmark_curve"):
            bench = metrics(curve_points(full["benchmark_curve"]))
        if (i + 1) % 50 == 0:
            print(f"...{i + 1}/{len(latest)}", file=sys.stderr, flush=True)

    if bench:
        print(f"BENCHMARK (NIFTY500) {START}->: cagr {bench['cagr']:.1%} "
              f"sharpe {bench['sharpe']:.2f} maxdd {bench['maxdd']:.1%}")
    print(f"{len(rows)} strategies sliced; window {START} -> "
          f"{rows[0]['end'] if rows else '?'}")

    full_rank = {m["sid"]: i for i, m in enumerate(
        sorted(rows, key=lambda x: -(x["full_cagr"] or 0)), 1)}

    def line(m, i):
        shift = full_rank[m["sid"]] - i
        return (f"{i:>3}. {m['sid']:<24} cagr {m['cagr']:>7.1%}  "
                f"sharpe {m['sharpe']:>5.2f}  maxdd {m['maxdd']:>7.1%}  "
                f"(10y-rank {full_rank[m['sid']]:>3}, {'+' if shift >= 0 else ''}{shift})")

    print("\nTOP 25 BY 5Y CAGR")
    for i, m in enumerate(sorted(rows, key=lambda x: -x["cagr"])[:25], 1):
        print(line(m, i))
    print("\nTOP 15 BY 5Y SHARPE")
    for i, m in enumerate(sorted(rows, key=lambda x: -x["sharpe"])[:15], 1):
        print(line(m, i))

    fams = {}
    for m in rows:
        fams.setdefault(m["sid"].split("_")[0], []).append(m["cagr"])
    print("\nFAMILY MEDIAN 5Y CAGR")
    for f, cs in sorted(fams.items(), key=lambda kv: -sorted(kv[1])[len(kv[1]) // 2]):
        cs.sort()
        print(f"  {f:<6} median {cs[len(cs) // 2]:>7.1%}   best {cs[-1]:>7.1%}   n={len(cs)}")

    with open("/tmp/slice5y_rows.json", "w") as fh:
        json.dump(rows, fh)


if __name__ == "__main__":
    main()
