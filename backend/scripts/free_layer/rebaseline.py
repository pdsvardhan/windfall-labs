"""iter-204 (adr-050 step 6): re-run the paper strategies on the current code + data, for a side-by-side.

Run twice — once with the pre-switch code (PYTHONPATH at a master checkout) and once with the new
code — each against a throwaway COPY of the meta DB (WINDFALL_DB), never the live one (ONE DOOR):

    WINDFALL_DB=/tmp/rb/meta_old.duckdb PYTHONPATH=<master>/backend \
        python scripts/free_layer/rebaseline.py --label old --configs /tmp/rb/configs.json --out /tmp/rb/old.json
    WINDFALL_DB=/tmp/rb/meta_new.duckdb PYTHONPATH=<worktree>/backend \
        python scripts/free_layer/rebaseline.py --label new --configs /tmp/rb/configs.json --out /tmp/rb/new.json
    python scripts/free_layer/rebaseline.py --compare /tmp/rb/old.json /tmp/rb/new.json

Each strategy runs from its own start to the latest bar (end=None), so the period after the frozen
harvest and after NSE's market-cap cutover is included. The Blend book (70/30 of two sleeves,
rebalanced each month) is reconstructed from the sleeves' monthly returns. The universe size is
counted at every month-end. Uses only functions both code versions have.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import pandas as pd

BLEND = ("BLEND_70_30", {"MOM_roc252_m_20": 0.7, "LV_atr_m_20": 0.3})


def run(label: str, configs_path: str, out: str) -> None:
    from windfall.data import trendlyne_store as ts
    from windfall.engine.backtest import run_backtest

    cfgs = json.load(open(configs_path))
    res: dict = {"label": label, "strategies": {}, "universe": {}}
    for sid, cfg in cfgs.items():
        cfg = {**cfg, "end": None}
        t0 = time.time()
        r = run_backtest(cfg)
        s = r.summary
        held = sorted({t.ticker for t in r.trades}) if r.trades else []
        res["strategies"][sid] = {
            "cagr": s.cagr, "sharpe": s.sharpe, "max_drawdown": s.max_drawdown,
            "total_return": s.total_return, "n_trades": s.n_trades, "exposure": s.exposure,
            "period": r.period, "monthly": r.monthly_returns, "held": held,
            "warnings": [w for w in r.warnings if "eligib" in w or "NSE" in w][:5],
            "secs": round(time.time() - t0, 1)}
        print(f"{label} {sid}: CAGR {s.cagr:.2%} Sharpe {s.sharpe:.2f} MaxDD {s.max_drawdown:.1%} "
              f"trades {s.n_trades} ({time.time() - t0:.0f}s)", flush=True)
    ends = pd.date_range("2016-06-30", pd.Timestamp.today(), freq="ME")
    for d in ends:
        res["universe"][str(d.date())] = len(ts.pit_universe(d))
    json.dump(res, open(out, "w"), default=str)
    print(f"{label}: universe month-ends {len(ends)}, written {out}")


def _blend(st: dict) -> dict | None:
    sid, w = BLEND
    m = {}
    for s, wt in w.items():
        if s not in st:
            return None
        m[s] = pd.Series({k: v for k, v in st[s]["monthly"]}) * wt
    r = pd.concat(m, axis=1).dropna().sum(axis=1)
    nav = (1 + r).cumprod()
    yrs = len(r) / 12
    cagr = nav.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else 0.0
    dd = (nav / nav.cummax() - 1).min()
    sharpe = (r.mean() / r.std() * 12 ** 0.5) if r.std() else 0.0
    return {"cagr": cagr, "max_drawdown": dd, "sharpe": sharpe, "n_trades": None}


def compare(old_p: str, new_p: str) -> None:
    old, new = json.load(open(old_p)), json.load(open(new_p))
    so, sn = old["strategies"], new["strategies"]
    for st in (so, sn):
        b = _blend(st)
        if b:
            st[BLEND[0]] = b
    print("strategy            | CAGR old -> new        | Sharpe old -> new | MaxDD old -> new     | trades old -> new")
    for sid in sorted(set(so) | set(sn)):
        a, b = so.get(sid, {}), sn.get(sid, {})
        f = lambda x, k, p: (f"{x[k]:{p}}" if x.get(k) is not None else "-")   # noqa: E731
        print(f"{sid:19s} | {f(a,'cagr','.2%'):>8s} -> {f(b,'cagr','.2%'):>8s} | "
              f"{f(a,'sharpe','.2f'):>5s} -> {f(b,'sharpe','.2f'):>5s} | "
              f"{f(a,'max_drawdown','.1%'):>7s} -> {f(b,'max_drawdown','.1%'):>7s} | "
              f"{a.get('n_trades', '-')} -> {b.get('n_trades', '-')}")
    for sid in sorted(set(so) & set(sn)):
        ho, hn = set(so[sid].get("held") or []), set(sn[sid].get("held") or [])
        if ho or hn:
            print(f"  {sid}: names traded only before {len(ho - hn)}, only after {len(hn - ho)} "
                  f"(e.g. after: {sorted(hn - ho)[:6]}; before: {sorted(ho - hn)[:6]})")
    uo, un = old["universe"], new["universe"]
    print("\nuniverse size at month-ends (old -> new):")
    for d in sorted(set(uo) & set(un)):
        if d.endswith(("-06-30", "-12-31")) or d >= "2024-01-31":
            print(f"  {d}: {uo[d]} -> {un[d]} ({un[d] - uo[d]:+d})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label")
    ap.add_argument("--configs")
    ap.add_argument("--out")
    ap.add_argument("--compare", nargs=2)
    a = ap.parse_args()
    if a.compare:
        compare(*a.compare)
    else:
        run(a.label, a.configs, a.out)
    sys.exit(0)
