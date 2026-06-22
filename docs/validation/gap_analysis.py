#!/usr/bin/env python3
"""WHY did we miss each Trendlyne pick? Per-miss root-cause classifier (verified, not assumed).

For every (period, gold-pick) Trendlyne selected that we did NOT, classify from our own data:
  NOT_IN_UNIVERSE  — name absent from our resolved tickers entirely (coverage gap).
  NO_DATA:<feat>   — in universe but the first filter feature is NaN at that date (factor horizon /
                     missing fundamental) — name CAN'T be evaluated, so the filter drops it.
  FAILED:<filter>  — in universe, feature present, but our value fails the threshold. Since pricing is
                     verified to ~0.003pp, a FAILED on a price-derived indicator (roc/rsi/sma) is a
                     pure FORMULA disagreement with Trendlyne, not a data gap. We print our value.
  RANKED_OUT       — eligible (passes every filter) but ranked outside our top-N (boundary churn).

Truth source = rs.entry_mask (engine's own eligibility); features recomputed only to EXPLAIN a False.

Usage:  python /tmp/gap_analysis.py 548042 548040 547990 ...
"""
import sys, re, collections
import numpy as np
import pandas as pd
from windfall import signals as ind
from windfall.strategy.schema import StrategyConfig
from windfall.strategy.resolve import resolve as do_resolve
from windfall.data import trendlyne_store as ts

WARMUP_DAYS = 420
NHOLD_DEFAULT = 10

# same TEST_TABLE as parity_multi.py (kept in sync)
TEST_TABLE = {
    "548012": dict(entry=["tl_durability > 55","tl_valuation > 50","tl_momentum > 60","adtv_cr > 10"],
        rank_by="tl_momentum", rank_order="desc", freq="monthly", floor=1000.0, nhold=10),
    "548776": dict(entry=["tl_durability > 55","tl_valuation > 50","tl_momentum > 60","adtv_cr > 10","tl_pe > 0"],
        rank_by="tl_pe", rank_order="asc", freq="monthly", floor=1000.0, nhold=10),
    "548042": dict(entry=["mcap > 1000","adtv_cr > 10","close > sma50","close > sma200","roc21 > 10","rsi14 > 60"],
        rank_by="roc21", rank_order="desc", freq="weekly", floor=1000.0, nhold=10),
    "548040": dict(entry=["mcap > 1000","adtv_cr > 10","tl_durability > 50","close > sma200","rsi14 > 40","rsi14 < 55"],
        rank_by="tl_momentum", rank_order="desc", freq="weekly", floor=1000.0, nhold=10),
    "548017": dict(entry=["tl_durability > 55","tl_valuation > 50","tl_momentum > 60","adtv_cr > 10","mcap > 1000","close > sma200"],
        rank_by="tl_momentum", rank_order="desc", freq="monthly", floor=1000.0, nhold=10),
    "548015": dict(entry=["tl_durability > 55","tl_valuation > 50","tl_momentum > 65","adtv_cr > 10","mcap > 1000"],
        rank_by="tl_momentum", rank_order="desc", freq="monthly", floor=1000.0, nhold=10),
    "548014": dict(entry=["tl_durability > 55","tl_valuation > 50","tl_momentum > 65","adtv_cr > 10","mcap > 1000"],
        rank_by="tl_momentum", rank_order="desc", freq="monthly", floor=1000.0, nhold=5),
    "547990": dict(entry=["mcap > 500","mcap < 50000","tl_durability > 50","rsi14 > 50","close > sma50","close > sma200","tl_pledge < 20","adtv_cr > 10","tl_pe < 100","tl_momentum > 60"],
        rank_by="tl_momentum", rank_order="desc", freq="monthly", floor=500.0, nhold=10),
    "547989": dict(entry=["mcap > 500","mcap < 50000","tl_durability > 50","rsi14 > 50","close > sma50","close > sma200","tl_pledge < 20","adtv_cr > 10","tl_pe < 100","tl_momentum > 60"],
        rank_by="tl_momentum", rank_order="desc", freq="weekly", floor=500.0, nhold=10),
    "547991": dict(entry=["mcap > 500","mcap < 50000","tl_durability > 50","rsi14 > 50","close > sma50","close > sma200","tl_pledge < 20","adtv_cr > 10","tl_pe < 100","tl_momentum > 60"],
        rank_by="tl_momentum", rank_order="desc", freq="monthly", floor=500.0, nhold=10),
    "547992": dict(entry=["mcap > 500","mcap < 50000","tl_durability > 50","rsi14 > 50","close > sma50","close > sma200","tl_pledge < 20","adtv_cr > 10","tl_pe < 100","tl_momentum > 60"],
        rank_by="tl_momentum", rank_order="desc", freq="quarterly", floor=500.0, nhold=10),
    "547994": dict(entry=["tl_durability > 55","tl_valuation > 50","tl_momentum > 60"],
        rank_by="tl_momentum", rank_order="desc", freq="weekly", floor=500.0, nhold=10),
    "547995": dict(entry=["tl_durability > 55","tl_valuation > 50","tl_momentum > 60"],
        rank_by="tl_momentum", rank_order="desc", freq="monthly", floor=500.0, nhold=10),
}

_RENAME = {a.upper(): b.upper() for a, b in
           ts._con().execute("SELECT old_sym, live_sym FROM rename_map WHERE live_sym IS NOT NULL").fetchall()}
def canon(s): return _RENAME.get(s.upper(), s.upper())

def parse_gold(path):
    periods, cur = [], None
    for line in open(path, encoding="utf-8"):
        parts = [x.strip() for x in line.rstrip("\n").split(",")]
        c0 = parts[0].strip('"')
        if " to " in c0:
            if cur: periods.append(cur)
            s, e = c0.split(" to "); cur = {"start": s.strip(), "picks": []}
        elif c0 == "" and len(parts) > 1 and parts[1]:
            m = re.search(r"\(([^)]*)\)", parts[1])
            if m: cur["picks"].append(canon(m.group(1).split("/")[-1].strip()))
    if cur: periods.append(cur)
    return [p for p in periods if p["picks"]]

_uow, _mp = ts.universe_over_window, ts.membership_panel
def resolve_current(cfg, floor):
    latest = ts._con().execute("SELECT MAX(date) FROM universe_membership").fetchone()[0]
    cur = ts.pit_universe(latest, floor_cr=floor)
    ts.universe_over_window = lambda s, e, floor_cr=floor: sorted(cur)
    ts.membership_panel = lambda symbols, dates, floor_cr=floor: pd.DataFrame(
        True, index=pd.DatetimeIndex(sorted(pd.to_datetime(dates).unique())),
        columns=[x.upper() for x in symbols])
    try:
        return do_resolve(cfg)
    finally:
        ts.universe_over_window, ts.membership_panel = _uow, _mp

def asof(df, d):
    idx = df.index[df.index <= pd.Timestamp(d)]
    return df.loc[idx[-1]] if len(idx) else None

# rebuild the price-derived + tl features a test's filters reference, the SAME way resolve.feat does
_FILT = re.compile(r"^\s*([a-z0-9_]+)\s*(<=|>=|<|>)\s*([a-z0-9_.]+)\s*$")
def build_features(rs, tickers, filters, floor):
    close = rs.close_adj
    tv = ts.traded_value_panel(tickers, str(close.index[0].date()), str(close.index[-1].date()))
    tv = tv.reindex(index=close.index, columns=tickers)
    feats = {}
    needed = set()
    for f in filters:
        m = _FILT.match(f)
        if not m: continue
        needed.add(m.group(1))
        if not re.match(r"^[0-9.]+$", m.group(3)): needed.add(m.group(3))
    for name in needed:
        pm = re.match(r"^(sma|roc|rsi)(\d+)$", name)
        if name in ("close",): feats[name] = close
        elif name == "adtv_cr": feats[name] = tv.rolling(20, min_periods=5).mean() / 1e7
        elif name == "mcap": feats[name] = ts.mcap_panel(tickers, close.index).reindex(index=close.index, columns=tickers)
        elif name in ("tl_durability","tl_valuation","tl_momentum"):
            feats[name] = ts.dvm_panel(name, tickers).reindex(index=close.index, columns=tickers).ffill()
        elif name in ("tl_pe","tl_pbv","tl_peg"):
            feats[name] = ts.valuation_panel(name, tickers).reindex(index=close.index, columns=tickers).ffill()
        elif name == "tl_pledge":
            feats[name] = ts.shareholding_panel(name, tickers, close.index).reindex(index=close.index, columns=tickers)
        elif pm:
            k, n = pm.group(1), int(pm.group(2))
            feats[name] = {"sma": ind.sma, "roc": ind.roc, "rsi": ind.rsi}[k](close, n)
    return feats

def classify_miss(sym, d, filters, feats, emask_row, rank_row, tickers_set):
    if sym not in tickers_set:
        return ("NOT_IN_UNIVERSE", None)
    # eligible? then it's a boundary/ranking miss
    if emask_row is not None and sym in emask_row.index and emask_row.get(sym) == True:
        rv = rank_row.get(sym) if rank_row is not None else None
        return ("RANKED_OUT", rv)
    # else explain the False: first filter that is NaN (no data) or fails (formula/threshold)
    for f in filters:
        m = _FILT.match(f)
        if not m: continue
        lhs, op, rhs = m.group(1), m.group(2), m.group(3)
        lv = feats.get(lhs)
        lrow = asof(lv, d) if lv is not None else None
        lval = lrow.get(sym) if lrow is not None and sym in lrow.index else np.nan
        if re.match(r"^[0-9.]+$", rhs):
            rval = float(rhs)
        else:
            rv2 = feats.get(rhs); rrow = asof(rv2, d) if rv2 is not None else None
            rval = rrow.get(sym) if rrow is not None and sym in rrow.index else np.nan
        if pd.isna(lval) or pd.isna(rval):
            return (f"NO_DATA:{lhs}", None)
        ok = {"<": lval < rval, ">": lval > rval, "<=": lval <= rval, ">=": lval >= rval}[op]
        if not ok:
            return (f"FAILED:{f}", (round(float(lval), 2), round(float(rval), 2)))
    return ("FAILED:unknown", None)

def run(tid):
    t = TEST_TABLE[tid]; nhold, floor = t["nhold"], t["floor"]
    asc = t["rank_order"] == "asc"
    periods = parse_gold(f"/tmp/parity_gold/gold_{tid}.csv")
    g0 = periods[0]["start"]; g1 = periods[-1]["start"]
    warm = str((pd.Timestamp(g0) - pd.Timedelta(days=WARMUP_DAYS)).date())
    # window end = last period start + buffer (we only need eligibility asof period starts)
    cfg = StrategyConfig(name=tid, data_source="trendlyne", entry_filters=t["entry"],
        rank_by=t["rank_by"], rank_order=t["rank_order"], n_holdings=nhold, weighting="equal",
        max_weight_per_stock=0.10, max_position_adtv_pct=1e9, rebalance=t["freq"],
        entry_fill="close", start=warm, end=g1, benchmark="NIFTY500")
    rs = resolve_current(cfg, floor)
    tickers = list(rs.close_adj.columns); tset = set(tickers)
    feats = build_features(rs, tickers, t["entry"], floor)

    # our picks per period
    our = {}
    for p in periods:
        elig = asof(rs.entry_mask, p["start"]); sc = asof(rs.rank_score, p["start"])
        if elig is None or sc is None: our[p["start"]] = []; continue
        cand = sc.where(elig.fillna(False)).dropna().sort_values(ascending=asc)
        our[p["start"]] = list(cand.head(nhold).index)

    cats = collections.Counter()
    failed_examples = collections.defaultdict(list)   # filter -> [(sym, our_val, thresh)]
    nodata_examples = collections.Counter()
    notuniv = collections.Counter()
    total_miss = 0
    for p in periods:
        d = p["start"]; emask_row = asof(rs.entry_mask, d); rank_row = asof(rs.rank_score, d)
        ourset = set(our[d])
        for g in p["picks"]:
            if g in ourset: continue
            total_miss += 1
            cat, info = classify_miss(g, d, t["entry"], feats, emask_row, rank_row, tset)
            head = cat.split(":")[0]
            cats[cat if head in ("NO_DATA", "FAILED") else head] += 1
            if head == "FAILED" and info: failed_examples[cat][:0] = [(g, info[0], info[1])]
            elif head == "NO_DATA": nodata_examples[cat] += 1
            elif head == "NOT_IN_UNIVERSE": notuniv[g] += 1

    print(f"\n{'='*76}\nTEST {tid}  filters={t['entry']}\n  rank={t['rank_by']} {t['rank_order']} nhold={nhold} | gold misses analysed: {total_miss}")
    for c, n in cats.most_common():
        print(f"   {n:4d} ({100*n/max(total_miss,1):2.0f}%)  {c}")
    if notuniv:
        print(f"   NOT_IN_UNIVERSE names (top): {notuniv.most_common(12)}")
    if nodata_examples:
        print(f"   NO_DATA breakdown: {dict(nodata_examples)}")
    for filt, exs in sorted(failed_examples.items(), key=lambda kv: -len(kv[1])):
        sample = exs[:8]
        print(f"   FAILED {filt}: {len(exs)} misses | our_val vs thresh e.g. " +
              ", ".join(f"{s}={v}(<>{th})" for s, v, th in sample))

if __name__ == "__main__":
    ids = sys.argv[1:] or list(TEST_TABLE)
    for tid in ids:
        try: run(tid)
        except Exception as e:
            import traceback; print(f"\n!!! {tid} FAILED: {e}"); traceback.print_exc()
