#!/usr/bin/env python3
"""Parametrised multi-backtest Trendlyne-parity deep-dive (TEST-ONLY; no engine change).

One harness, all ~10 backtests. Config is driven by TEST_TABLE (mirrors
docs/validation/multi-backtest-parity-plan.md) instead of parity.py's hardcoded cfg.

Per test it runs the full Test-A 5-section reconciliation in PHASE A (current
membership = Trendlyne's survivorship basis):
  1. SELECTION  — name-by-name overlap; Trendlyne-only vs ours-only frequency; PE/rank boundary.
  2. PRICING    — our adjusted price vs Trendlyne's CSV price, per stock-period (target ~0.04pp).
  3. RETURN DECOMPOSITION — gold@TLpx (=avg_row) vs gold@ourpx (pricing) vs ourpicks@ourpx (selection).
  4. THIN PERIODS & CASH DRAG — fixed NHOLD slots vs fully-invested.
  5. LOCALIZE   — per-period gold@ourpx vs avg_row residual (where pricing leaks).
Then a PHASE B (PIT survivorship-free) compact summary: universe size, our-pick overlap, our NAV.

A final `SUMMARY|...` line per test is emitted for the consolidated cross-test table.

Usage:  python /tmp/parity_multi.py 548012
        python /tmp/parity_multi.py all
"""
import sys, re, collections
import numpy as np
import pandas as pd
from windfall.strategy.schema import StrategyConfig
from windfall.strategy.resolve import resolve as do_resolve
from windfall.data import trendlyne_store as ts

# ---- per-test config (see multi-backtest-parity-plan.md table) ----
# freq: weekly|monthly|quarterly (engine literals).  floor = universe Rs-cr floor.  nhold = fixed slots.
TEST_TABLE = {
    "548012": dict(name="Tradeable (DVM-mom)",
        entry=["tl_durability > 55", "tl_valuation > 50", "tl_momentum > 60", "adtv_cr > 10"],
        rank_by="tl_momentum", rank_order="desc", freq="monthly", floor=1000.0, nhold=10),
    "548776": dict(name="Test A (value/PE)",
        entry=["tl_durability > 55", "tl_valuation > 50", "tl_momentum > 60", "adtv_cr > 10", "tl_pe > 0"],
        rank_by="tl_pe", rank_order="asc", freq="monthly", floor=1000.0, nhold=10),
    "548042": dict(name="Short-term breakout (pure technical)",
        entry=["mcap > 1000", "adtv_cr > 10", "close > sma50", "close > sma200", "roc21 > 10", "rsi14 > 60"],
        rank_by="roc21", rank_order="desc", freq="weekly", floor=1000.0, nhold=10),
    "548040": dict(name="Pullback in uptrend (mean-reversion)",
        entry=["mcap > 1000", "adtv_cr > 10", "tl_durability > 50", "close > sma200", "rsi14 > 40", "rsi14 < 55"],
        rank_by="tl_momentum", rank_order="desc", freq="weekly", floor=1000.0, nhold=10),
    "548017": dict(name="Trend/regime proxy",
        entry=["tl_durability > 55", "tl_valuation > 50", "tl_momentum > 60", "adtv_cr > 10", "mcap > 1000", "close > sma200"],
        rank_by="tl_momentum", rank_order="desc", freq="monthly", floor=1000.0, nhold=10),
    "548015": dict(name="Tighter momentum (>65)",
        entry=["tl_durability > 55", "tl_valuation > 50", "tl_momentum > 65", "adtv_cr > 10", "mcap > 1000"],
        rank_by="tl_momentum", rank_order="desc", freq="monthly", floor=1000.0, nhold=10),
    "548014": dict(name="Tighter momentum (20% max weight = 5 slots)",
        entry=["tl_durability > 55", "tl_valuation > 50", "tl_momentum > 65", "adtv_cr > 10", "mcap > 1000"],
        rank_by="tl_momentum", rank_order="desc", freq="monthly", floor=1000.0, nhold=5),
    "547990": dict(name="Windfall v2.2 (monthly)",
        entry=["mcap > 500", "mcap < 50000", "tl_durability > 50", "rsi14 > 50", "close > sma50",
               "close > sma200", "tl_pledge < 20", "adtv_cr > 10", "tl_pe < 100", "tl_momentum > 60"],
        rank_by="tl_momentum", rank_order="desc", freq="monthly", floor=500.0, nhold=10),
    "547989": dict(name="Windfall v2.2 (weekly)",
        entry=["mcap > 500", "mcap < 50000", "tl_durability > 50", "rsi14 > 50", "close > sma50",
               "close > sma200", "tl_pledge < 20", "adtv_cr > 10", "tl_pe < 100", "tl_momentum > 60"],
        rank_by="tl_momentum", rank_order="desc", freq="weekly", floor=500.0, nhold=10),
    # --- restored 2026-06-25 (Session 2 revalidation): the 4 deep-history / no-floor tests trimmed
    #     from parity_multi after the 2026-06-22 baseline; still present in gap_analysis.py. Configs
    #     re-confirmed against owner Trendlyne screenshots (547992 full query expanded). ---
    "547991": dict(name="Windfall v2.2 (monthly, full 2021-26)",
        entry=["mcap > 500", "mcap < 50000", "tl_durability > 50", "rsi14 > 50", "close > sma50",
               "close > sma200", "tl_pledge < 20", "adtv_cr > 10", "tl_pe < 100", "tl_momentum > 60"],
        rank_by="tl_momentum", rank_order="desc", freq="monthly", floor=500.0, nhold=10),
    "547992": dict(name="Windfall v2.2 (quarterly, 2013-26 deep history)",
        entry=["mcap > 500", "mcap < 50000", "tl_durability > 50", "rsi14 > 50", "close > sma50",
               "close > sma200", "tl_pledge < 20", "adtv_cr > 10", "tl_pe < 100", "tl_momentum > 60"],
        rank_by="tl_momentum", rank_order="desc", freq="quarterly", floor=500.0, nhold=10),
    "547994": dict(name="Pure DVM (weekly, no liquidity floor)",
        entry=["tl_durability > 55", "tl_valuation > 50", "tl_momentum > 60"],
        rank_by="tl_momentum", rank_order="desc", freq="weekly", floor=500.0, nhold=10),
    "547995": dict(name="Pure DVM (monthly, no liquidity floor)",
        entry=["tl_durability > 55", "tl_valuation > 50", "tl_momentum > 60"],
        rank_by="tl_momentum", rank_order="desc", freq="monthly", floor=500.0, nhold=10),
}

# rename old->live so external gold tickers join our current-symbol universe (iter-34/adr-025)
# Warmup lead before the gold window so ROLLING features (sma50/200, rsi14, roc21, adtv) are warm at
# period 1. sma200 needs 200 TRADING days (~280 cal); 120 cal (~80 trading) starved the technical
# screens (548042/548040/v2.2) and emptied their early periods -> spurious low overlap. 420 cal days
# (~290 trading) covers sma200 with buffer. Harmless to the DVM screens (tl_* factors are point-in-
# time, not rolling; their period-1 picks are unchanged) — longer warmup only makes features valid
# earlier, never alters later-period picks.
WARMUP_DAYS = 420

_RENAME = {a.upper(): b.upper() for a, b in
           ts._con().execute("SELECT old_sym, live_sym FROM rename_map WHERE live_sym IS NOT NULL").fetchall()}
def canon(s): return _RENAME.get(s.upper(), s.upper())
CA_UNC = set(ts.ca_uncertain_symbols())


def parse_gold(path):
    """Returns periods: [{start,end,rows:[(sym,sp,ep,ch)],avg,nav,picks:[sym]}]. canon-resolved syms."""
    periods, cur = [], None
    for line in open(path, encoding="utf-8"):
        parts = [x.strip() for x in line.rstrip("\n").split(",")]
        c0 = parts[0].strip('"')
        if " to " in c0:
            if cur: periods.append(cur)
            s, e = c0.split(" to ")
            cur = {"start": s.strip(), "end": e.strip(), "rows": [], "picks": [], "avg": None, "nav": None}
        elif c0 == "Total Change":
            try: cur["avg"] = float(parts[5])
            except Exception: pass
            try: cur["nav"] = float(parts[7])
            except Exception: pass
        elif c0 == "" and len(parts) > 1 and parts[1]:
            m = re.search(r"\(([^)]*)\)", parts[1])
            sym = canon(m.group(1).split("/")[-1].strip()) if m else None
            try: sp, ep, ch = float(parts[2]), float(parts[3]), float(parts[4])
            except Exception: sp = ep = ch = None
            if sym and sp:
                cur["rows"].append((sym, sp, ep, ch)); cur["picks"].append(sym)
    if cur: periods.append(cur)
    return [p for p in periods if p["rows"]]


def build_cfg(tid, warm, end):
    t = TEST_TABLE[tid]
    return StrategyConfig(
        name=tid, data_source="trendlyne", entry_filters=t["entry"],
        rank_by=t["rank_by"], rank_order=t["rank_order"], n_holdings=t["nhold"],
        weighting="equal", max_weight_per_stock=0.10, max_position_adtv_pct=1e9,
        rebalance=t["freq"], entry_fill="close", start=warm, end=end, benchmark="NIFTY500")


_uow, _mp = ts.universe_over_window, ts.membership_panel
def resolve_mode(cfg, mode, floor):
    if mode == "current":
        latest = ts._con().execute("SELECT MAX(date) FROM universe_membership").fetchone()[0]
        cur = ts.pit_universe(latest, floor_cr=floor)
        ts.universe_over_window = lambda s, e, floor_cr=floor: sorted(cur)
        ts.membership_panel = lambda symbols, dates, floor_cr=floor: pd.DataFrame(
            True, index=pd.DatetimeIndex(sorted(pd.to_datetime(dates).unique())),
            columns=[x.upper() for x in symbols])
    else:
        ts.universe_over_window = lambda s, e, floor_cr=floor: _uow(s, e, floor_cr=floor)
        ts.membership_panel = lambda symbols, dates, floor_cr=floor: _mp(symbols, dates, floor_cr=floor)
    try:
        return do_resolve(cfg)
    finally:
        ts.universe_over_window, ts.membership_panel = _uow, _mp


def asof_row(df, d):
    idx = df.index[df.index <= pd.Timestamp(d)]
    return df.loc[idx[-1]] if len(idx) else None


def our_picks(rs, periods, nhold, asc):
    out, cand_full = {}, {}
    for p in periods:
        elig = asof_row(rs.entry_mask, p["start"]); sc = asof_row(rs.rank_score, p["start"])
        if elig is None or sc is None: out[p["start"]] = []; continue
        cand = sc.where(elig.fillna(False)).dropna().sort_values(ascending=asc)
        out[p["start"]] = list(cand.head(nhold).index); cand_full[p["start"]] = cand
    return out, cand_full


def run_test(tid):
    t = TEST_TABLE[tid]; nhold, floor, asc = t["nhold"], t["floor"], (t["rank_order"] == "asc")
    gold = f"/tmp/parity_gold/gold_{tid}.csv"
    periods = parse_gold(gold)
    g_start, g_end = periods[0]["start"], periods[-1]["end"]
    warm = str((pd.Timestamp(g_start) - pd.Timedelta(days=WARMUP_DAYS)).date())
    cfg = build_cfg(tid, warm, g_end)

    print("#" * 78)
    print(f"# TEST {tid} — {t['name']}")
    print(f"# filters: {t['entry']}")
    print(f"# rank: {t['rank_by']} {t['rank_order']} | freq={t['freq']} floor={floor} nhold={nhold}")
    print(f"# window: {g_start} -> {g_end} ({len(periods)} periods); resolve warmup from {warm}")
    print("#" * 78)

    rsA = resolve_mode(cfg, "current", floor)
    our, cand_full = our_picks(rsA, periods, nhold, asc)

    gold_syms = sorted({r[0] for p in periods for r in p["rows"]})
    allsyms = sorted(set(gold_syms) | {s for v in our.values() for s in v})
    px = ts.adjusted_close_panel(allsyms, warm, g_end, "close")
    def aspx(sym, d):
        if sym not in px.columns: return None
        w = px[sym][px[sym].index <= pd.Timestamp(d)].dropna()
        return float(w.iloc[-1]) if len(w) else None

    # ---- SECTION 1: SELECTION ----
    print("\n=== 1. SELECTION (name-by-name vs Trendlyne, Phase A current-membership) ===")
    tl_only, ours_only, ov_list = collections.Counter(), collections.Counter(), []
    for p in periods:
        g = set(r[0] for r in p["rows"]); o = set(our[p["start"]])
        ov_list.append(len(g & o))
        for s in (g - o): tl_only[s] += 1
        for s in (o - g): ours_only[s] += 1
    tot = sum(len(set(r[0] for r in p["rows"])) for p in periods); hit = sum(ov_list)
    avg_ov = np.mean(ov_list) if ov_list else 0
    print(f"periods={len(periods)} avg_overlap={avg_ov:.1f}/{nhold} total_matches={hit}/{tot}={100*hit/max(tot,1):.0f}%")
    print(f"distinct TL-only names={len(tl_only)} slot-misses={sum(tl_only.values())} | most common: {tl_only.most_common(10)}")
    print(f"distinct ours-only names={len(ours_only)} slot-extras={sum(ours_only.values())} | most common: {ours_only.most_common(10)}")
    print("  boundary (first 3 periods, rank #nhold-1..nhold+3):")
    for p in periods[:3]:
        g = set(r[0] for r in p["rows"]); o = set(our[p["start"]]); cand = cand_full.get(p["start"])
        print(f"   {p['start']}: TL-only={sorted(g-o)} ours-only={sorted(o-g)}")
        if cand is not None and len(cand) >= nhold + 2:
            edge = cand.iloc[max(0, nhold-2):nhold+3]
            print(f"     our rank #{nhold-1}-{nhold+3}: " + str([f"{n}={v:.1f}" for n, v in edge.items()]))

    # ---- SECTION 2: PRICING ----
    print("\n=== 2. PRICING (our adj price vs Trendlyne CSV price, per stock-period) ===")
    diffs, worst, ca_flag = [], [], []
    for p in periods:
        for sym, sp, ep, ch in p["rows"]:
            os, oe = aspx(sym, p["start"]), aspx(sym, p["end"])
            if os and oe and sp > 0 and ep > 0 and ch is not None:
                ourc = (oe / os - 1) * 100
                diffs.append(abs(ourc - ch)); worst.append((abs(ourc - ch), p["start"], sym, ch, round(ourc, 1)))
                rs_, re_ = os / sp, oe / ep
                if abs(rs_ - re_) / max(abs(rs_), 1e-9) > 0.05:
                    ca_flag.append((p["start"], sym, round(rs_, 3), round(re_, 3), ch, round(ourc, 1)))
    missing_gold = [s for s in gold_syms if s not in px.columns]
    if diffs:
        d = np.array(diffs)
        print(f"stock-periods={len(d)} mean|Δ|={d.mean():.3f}pp median={np.median(d):.3f}pp p95={np.percentile(d,95):.2f}pp max={d.max():.2f}pp")
        print(f"  within 0.5pp={100*(d<0.5).mean():.0f}% within 1pp={100*(d<1).mean():.0f}% | gold names unpriceable={len(missing_gold)}/{len(gold_syms)}")
        print(f"  CA-adj mismatches (ratio start->end jumped >5%): {len(ca_flag)}")
        for r in sorted(ca_flag)[:8]:
            print(f"    {r[0]} {r[1]:12s} ratio {r[2]}->{r[3]} tl_chg={r[4]:+.1f}% our_chg={r[5]:+.1f}%")
        print("  worst 6 |Δ|:", [(w[1], w[2], f"tl={w[3]}", f"ours={w[4]}") for w in sorted(worst, reverse=True)[:6]])
        mean_abs = d.mean()
    else:
        print("  (no priced stock-periods)"); mean_abs = float('nan')
    print(f"  gold names we cannot price at all ({len(missing_gold)}): {missing_gold[:20]}")

    # ---- SECTION 3: RETURN DECOMPOSITION ----
    print("\n=== 3. RETURN DECOMPOSITION (compounded NAV, ÷nhold fixed slots) ===")
    def navlast(fn):
        nav = 100.0
        for p in periods: nav *= (1 + fn(p))
        return nav
    # gold_tlpx keeps ALL names (it must equal Trendlyne's reported NAV — validates NAV=compounded
    # avg_row). The OUR-price reconstructions park ca_uncertain names as cash (parity.py methodology):
    # we cannot trust our OR Trendlyne's price for an unconfirmable corporate action, so we don't grade
    # the engine on them. Count how many slot-instances get parked, for transparency.
    ca_parked = [0]
    def gold_tlpx(p):  return sum(r[3] for r in p["rows"][:nhold]) / 100.0 / nhold
    def gold_ourpx(p):
        t_ = 0.0
        for sym, sp, ep, ch in p["rows"][:nhold]:
            if sym in CA_UNC: ca_parked[0] += 1; continue
            os, oe = aspx(sym, p["start"]), aspx(sym, p["end"])
            if os and oe and os > 0: t_ += oe / os - 1
        return t_ / nhold
    def our_ourpx(p):
        t_ = 0.0
        for sym in our[p["start"]][:nhold]:
            if sym in CA_UNC: continue
            os, oe = aspx(sym, p["start"]), aspx(sym, p["end"])
            if os and oe and os > 0: t_ += oe / os - 1
        return t_ / nhold
    gold_nav = periods[-1]["nav"]; nav_tlpx = navlast(gold_tlpx)
    nav_ourpx = navlast(gold_ourpx); nav_ours = navlast(our_ourpx)
    print(f"  Trendlyne reported NAV                 : {gold_nav:.1f}  ({gold_nav-100:+.1f}%)")
    print(f"  gold picks @ Trendlyne prices (avg_row): {nav_tlpx:.1f}  ({nav_tlpx-100:+.1f}%)")
    print(f"  gold picks @ OUR prices (PRICING)      : {nav_ourpx:.1f}  ({nav_ourpx-100:+.1f}%)  <- == above => prices reproduce TL")
    print(f"  OUR picks  @ OUR prices (+ SELECTION)  : {nav_ours:.1f}  ({nav_ours-100:+.1f}%)")
    print(f"  (ca_uncertain slot-instances parked as cash in OUR-price recon: {ca_parked[0]})")

    # ---- SECTION 4: THIN PERIODS & CASH DRAG ----
    print("\n=== 4. THIN PERIODS & CASH DRAG ===")
    cnts = collections.Counter(len(p["rows"]) for p in periods)
    thin = [p for p in periods if len(p["rows"]) < nhold]
    print(f"  gold pick-count distribution: {dict(sorted(cnts.items()))}")
    print(f"  periods with <{nhold} gold names: {len(thin)} (Trendlyne parks empty slots in cash)")
    fullinv = 100.0
    for p in periods:
        rows = p["rows"]; fullinv *= (1 + (np.mean([r[3] for r in rows]) / 100.0 if rows else 0))
    print(f"  if FULLY invested (÷actual count): {fullinv:.1f}  vs ÷{nhold} {gold_nav:.1f}  -> cash drag = {fullinv-gold_nav:+.0f} NAV pts")

    # ---- SECTION 5: LOCALIZE pricing residual ----
    print("\n=== 5. LOCALIZE (per-period gold@ourpx vs avg_row, |Δ|>0.4pp) ===")
    nloc = 0
    for i, p in enumerate(periods):
        a = gold_ourpx(p) * 100; b = (p["avg"] if p["avg"] is not None else 0)
        if abs(a - b) > 0.4:
            npriced = sum(1 for sym, sp, ep, ch in p["rows"][:nhold] if aspx(sym, p["start"]) and aspx(sym, p["end"]))
            print(f"   [{i:2d}] {p['start']} n_gold={len(p['rows'])} priced_by_us={npriced} | ourpx={a:+.2f}% avg_row={b:+.2f}% Δ={a-b:+.2f}pp")
            nloc += 1
    if nloc == 0: print("   (no period exceeds 0.4pp — pricing tracks avg_row cleanly)")

    # ---- PHASE B: PIT survivorship-free summary ----
    print("\n=== PHASE B (PIT survivorship-free) summary ===")
    rsB = resolve_mode(cfg, "pit", floor)
    ourB, _ = our_picks(rsB, periods, nhold, asc)
    allsymsB = sorted(set(gold_syms) | {s for v in ourB.values() for s in v})
    pxB = ts.adjusted_close_panel(allsymsB, warm, g_end, "close")
    def aspxB(sym, d):
        if sym not in pxB.columns: return None
        w = pxB[sym][pxB[sym].index <= pd.Timestamp(d)].dropna()
        return float(w.iloc[-1]) if len(w) else None
    ovB = sum(len(set(p["picks"]) & set(ourB[p["start"]])) for p in periods)
    navB = 100.0
    for p in periods:
        tr = 0.0
        for sym in ourB[p["start"]][:nhold]:
            os, oe = aspxB(sym, p["start"]), aspxB(sym, p["end"])
            if os and oe and os > 0: tr += oe / os - 1
        navB *= (1 + tr / nhold)
    print(f"  PIT universe size={len(rsB.tickers)} | our-pick overlap vs gold={ovB}/{tot}={100*ovB/max(tot,1):.0f}% | OUR-picks NAV={navB:.1f} ({navB-100:+.1f}%)")

    # ---- machine-readable summary ----
    print(f"\nSUMMARY|{tid}|{t['name']}|periods={len(periods)}|overlapA={100*hit/max(tot,1):.0f}%|"
          f"priceMeanAbs={mean_abs:.3f}|goldNAV={gold_nav:.1f}|goldOurpx={nav_ourpx:.1f}|"
          f"ourNAV_A={nav_ours:.1f}|ourNAV_B={navB:.1f}|overlapB={100*ovB/max(tot,1):.0f}%|"
          f"unpriced={len(missing_gold)}|thin={len(thin)}|caFlags={len(ca_flag)}")
    for w in rsA.warnings[:2]: print("  warnA:", w[:120])


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    ids = list(TEST_TABLE) if arg == "all" else [arg]
    for tid in ids:
        try:
            run_test(tid)
        except Exception as e:
            import traceback
            print(f"\n!!! TEST {tid} FAILED: {e}")
            traceback.print_exc()
        print("\n")
