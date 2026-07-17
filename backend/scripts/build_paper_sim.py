"""Build backend/data/paper_sim.json — the clearly-labeled 'what if entries had started
2026-06-29' simulation shown next to the live paper books (owner decision, iteration 94:
the honest alternative to backdating the live record, which was declined as look-ahead).

Mechanical engine runs, next-open fills, full costs — no discretion anywhere. Rerunnable;
each run overwrites the file. BLEND_70_30 goes through the rotation endpoint in fixed-weight
mode; the other four are direct backtests of their stored configs.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = os.environ.get("WINDFALL_API", "http://127.0.0.1:8505")
SIM_START = "2026-06-29"
OUT = Path(__file__).resolve().parents[1] / "data" / "paper_sim.json"
DIRECT = ["DVM_user", "DVM_dm_m_20", "MOM_roc252_m_20", "CMP_valmom_m_20"]
BLEND_SLEEVES = ["MOM_roc252_m_10", "LV_atr_m_10"]
BLEND_WEIGHTS = [0.7, 0.3]


def call(path: str, body: dict | None = None, timeout: float = 600.0):
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"}, method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def get_config(sid: str) -> dict:
    return call(f"/api/strategies/{sid}")["config"]


def norm_points(eq) -> list[list]:
    pts = (sorted(eq.items()) if isinstance(eq, dict)
           else [(p[0], p[1]) if isinstance(p, (list, tuple))
                 else (p.get("date"), p.get("equity", p.get("value"))) for p in eq])
    pts = [(d, v) for d, v in pts if v is not None]
    if not pts:
        return []
    v0 = pts[0][1]
    return [[d, round(v / v0 - 1, 6)] for d, v in pts]


def main():
    books: dict[str, dict] = {}
    for sid in DIRECT:
        cfg = get_config(sid)
        cfg["start"], cfg["end"] = SIM_START, None
        cfg["name"] = f"{sid}__sim0629"
        try:
            res = call("/api/backtests", {"config": cfg, "save": False})
            books[sid] = {"points": norm_points(res.get("equity_curve") or []),
                          "ret": (res.get("summary") or {}).get("total_return")}
        except Exception as exc:  # noqa: BLE001
            books[sid] = {"points": [], "error": str(exc)[:200]}

    # BLEND via rotation fixed-weight mode; the endpoint has a known transient flake
    # (todo 250) so retry once before recording an error.
    sleeves = []
    for sid in BLEND_SLEEVES:
        c = get_config(sid)
        c["start"], c["end"] = SIM_START, None
        sleeves.append(c)
    for attempt in (1, 2):
        try:
            res = call("/api/rotation", {"sleeves": sleeves, "weights": BLEND_WEIGHTS,
                                         "rebalance": "monthly", "capital": 100000,
                                         "name": "BLEND_70_30__sim0629"})
            eq = res.get("equity_curve") or (res.get("result") or {}).get("equity_curve") or []
            books["BLEND_70_30"] = {"points": norm_points(eq),
                                    "ret": (res.get("summary") or {}).get("total_return")}
            break
        except Exception as exc:  # noqa: BLE001
            if attempt == 2:
                books["BLEND_70_30"] = {"points": [], "error": str(exc)[:200]}
            else:
                time.sleep(2)

    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sim_start": SIM_START,
        "label": "SIMULATED — mechanical engine run from 2026-06-29; NOT the live record",
        "books": books,
    }, indent=1))
    print(f"wrote {OUT}:",
          {k: (len(v["points"]) or v.get("error", "?")) for k, v in books.items()})


if __name__ == "__main__":
    main()
