"""Multi-strategy rotation overlay — a fund-of-funds across self-timed sleeves + cash.

The user's deployment plan: run 2-3 different strategies (each self-timed via factor_timing) with
~Rs1L each, monthly rotate the money to whichever sleeve is working, and stand in cash when none
are. This module backtests that allocation rule.

It treats each sleeve's backtest equity curve as a tradable "fund": at each rotation it ranks the
sleeves by trailing return, allocates equally to the working ones (trailing return > momentum_floor,
capped at top_k), and parks the rest in cash. The within-sleeve stock costs are already baked into
each sleeve's NAV; `switch_cost_bps` is charged on the FUND-LEVEL turnover when the allocation
changes.

APPROXIMATION (stated, not hidden — anti-gaslight): the fund-level switch cost does NOT net out
stock-level overlap between sleeves (two momentum sleeves can share names, so the real turnover of
moving between them is lower than the fund-level weight change implies). So the modelled switch cost
is a CONSERVATIVE UPPER BOUND. The realistic floor is each sleeve's own NAV (already cost-laden);
the truth is between. Reported in `warnings`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import metrics
from .backtest import _rebalance_dates, run_backtest


def run_rotation(
    sleeves: list[dict],
    rebalance: str = "monthly",
    lookback_days: int = 63,
    top_k: int | None = None,
    momentum_floor: float = 0.0,
    switch_cost_bps: float = 20.0,
    capital: float = 1_000_000.0,
    benchmark: str = "NIFTY500",
    name: str = "rotation",
    weights: list[float] | None = None,
) -> dict:
    if len(sleeves) < 2:
        raise ValueError("rotation needs at least 2 sleeves")
    if lookback_days < 2:
        raise ValueError("lookback_days must be at least 2")

    # Fixed-weight (static-blend) mode: when explicit per-sleeve weights are given, the book holds
    # that allocation rebalanced every `rebalance` period with real switch costs — NO trailing-return
    # ranking. A 70/30 momentum/low-vol blend is the headline use (adr-035: diversification beats
    # trailing-return rotation). Weights are normalized; they may sum < 1 to hold a fixed cash sleeve.
    fixed_mode = weights is not None
    if fixed_mode:
        if len(weights) != len(sleeves):
            raise ValueError("weights must have one entry per sleeve")
        if any(w < 0 for w in weights):
            raise ValueError("weights must be non-negative")
        wsum = float(sum(weights))
        if wsum <= 0:
            raise ValueError("weights must sum to a positive value")
        # sum<=1 -> absolute weights, cash = 1-sum; sum>1 -> relative weights, normalized (no cash)
        norm_w = [w / wsum for w in weights] if wsum > 1.0 + 1e-9 else list(weights)

    # 1) Run each sleeve; collect its daily NAV curve.
    sleeve_names: list[str] = []
    nav_cols: dict[str, pd.Series] = {}
    sleeve_summaries: list[dict] = []
    bench_curve: pd.Series | None = None
    for idx, cfg in enumerate(sleeves):
        res = run_backtest(cfg)
        nm = res.name or f"sleeve_{idx}"
        if nm in nav_cols:                       # disambiguate duplicate sleeve names
            nm = f"{nm}#{idx}"
        sleeve_names.append(nm)
        nav_cols[nm] = pd.Series({pd.Timestamp(d): float(v) for d, v in res.equity_curve})
        sleeve_summaries.append({"name": nm, "summary": res.summary.model_dump()})
        if bench_curve is None and res.benchmark_curve:
            bench_curve = pd.Series({pd.Timestamp(d): float(v) for d, v in res.benchmark_curve})

    # 2) Align sleeves to their common window; normalize each to 1.0 at the common start.
    warm = 0 if fixed_mode else lookback_days   # fixed weights need no trailing-return warmup
    nav_df = pd.DataFrame(nav_cols).sort_index().ffill().dropna()
    if len(nav_df) < warm + 2:
        raise ValueError("sleeves do not overlap enough to rotate over the lookback window")
    norm = nav_df / nav_df.iloc[0]
    sret = norm.pct_change().fillna(0.0)         # per-sleeve daily returns
    dates = norm.index
    rotate_on = _rebalance_dates(dates, rebalance)

    # 3) Walk the combined book day by day.
    cap = float(capital)
    combined_vals: list[float] = []
    cash_weight_hist: list[float] = []
    weights = {nm: 0.0 for nm in sleeve_names}   # start fully in cash until the lookback warms
    cash_w = 1.0
    total_turnover = 0.0
    alloc_log: list[dict] = []

    for t, day in enumerate(dates):
        # a) grow the book by yesterday->today sleeve returns at yesterday's weights (held overnight)
        if t > 0:
            growth = sum(weights[nm] * sret.iloc[t][nm] for nm in sleeve_names)
            cap *= (1.0 + growth)               # cash earns 0 (no rate assumed — conservative)

        # b) rebalance decision at the close. Fixed mode: re-assert the target weights (turnover is
        # only drift correction). Rank mode: rank sleeves by trailing-lookback return, reallocate.
        if day in rotate_on and t >= warm:
            trailing = None
            if fixed_mode:
                new_w = {nm: norm_w[k] for k, nm in enumerate(sleeve_names)}
            else:
                trailing = {nm: float(norm.iloc[t][nm] / norm.iloc[t - lookback_days][nm] - 1.0)
                            for nm in sleeve_names}
                working = sorted([nm for nm, r in trailing.items() if r > momentum_floor],
                                 key=lambda nm: trailing[nm], reverse=True)
                if top_k is not None:
                    working = working[:top_k]
                new_w = {nm: 0.0 for nm in sleeve_names}
                if working:
                    eq = 1.0 / len(working)
                    for nm in working:
                        new_w[nm] = eq
            new_cash = 1.0 - sum(new_w.values())
            # fund-level turnover (incl. the cash leg) -> conservative switch cost
            turn = sum(abs(new_w[nm] - weights[nm]) for nm in sleeve_names) + abs(new_cash - cash_w)
            total_turnover += turn
            cap *= (1.0 - turn * switch_cost_bps / 10_000.0)
            weights, cash_w = new_w, new_cash
            entry = {"date": str(day.date()),
                     "weights": {nm: round(weights[nm], 4) for nm in sleeve_names if weights[nm] > 0},
                     "cash": round(cash_w, 4)}
            if trailing is not None:
                entry["trailing"] = {nm: round(trailing[nm], 4) for nm in sleeve_names}
            alloc_log.append(entry)

        combined_vals.append(cap)
        cash_weight_hist.append(cash_w)

    nav = pd.Series(combined_vals, index=dates)
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-6)
    annual_turnover = total_turnover / (2 * years)
    exposure = float(np.mean([1.0 - c for c in cash_weight_hist])) if cash_weight_hist else 0.0

    bench = bench_curve.reindex(nav.index).ffill() if bench_curve is not None else None
    summary = metrics.compute_summary(nav, [], bench, years, annual_turnover, exposure)
    dd = metrics.drawdown_series(nav)

    warnings = [
        ("rotation switch cost is modelled at the FUND level on inter-sleeve turnover and does NOT "
         "net stock-level overlap between sleeves — it is a CONSERVATIVE UPPER BOUND on switching "
         "cost; the realistic floor is each sleeve's own (already cost-laden) NAV."),
    ]
    if fixed_mode:
        warnings.append(
            f"FIXED-WEIGHT static blend: target {dict(zip(sleeve_names, [round(w, 3) for w in norm_w]))}"
            f" re-asserted every {rebalance} (no trailing-return ranking).")
    else:
        warnings.append(
            f"sleeves rotate {rebalance}; a sleeve is 'working' when its trailing {lookback_days}-day "
            f"return exceeds {momentum_floor:+.0%}; book holds cash until the lookback window warms.")

    return {
        "name": name,
        "period": {"start": str(dates[0].date()), "end": str(dates[-1].date()),
                   "years": round(years, 2), "n_days": int(len(dates))},
        "summary": summary.model_dump(),
        "equity_curve": [[str(d.date()), round(float(v), 2)] for d, v in nav.items()],
        "drawdown_curve": [[str(d.date()), round(float(v), 5)] for d, v in dd.items()
                           if np.isfinite(v)],
        "monthly_returns": metrics.monthly_returns(nav),
        "benchmark_curve": ([[str(d.date()), round(float(v), 2)] for d, v in bench.items()
                             if np.isfinite(v)] if bench is not None else []),
        "sleeves": sleeve_summaries,
        "allocations": alloc_log,
        "config": {"mode": "fixed-weight" if fixed_mode else "trailing-return",
                   "weights": (norm_w if fixed_mode else None),
                   "rebalance": rebalance, "lookback_days": lookback_days, "top_k": top_k,
                   "momentum_floor": momentum_floor, "switch_cost_bps": switch_cost_bps,
                   "capital": capital},
        "warnings": warnings,
    }
