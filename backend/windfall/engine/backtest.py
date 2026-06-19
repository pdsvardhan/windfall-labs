"""Deterministic rebalance-and-hold simulator with daily, explicit exits.

Decision at the close of day t uses only data up to t; fills at the next bar's open (no look-ahead).
Between rebalances, stops / targets / trailing / time-exits are checked every day. Costs are
deducted on every entry and exit, and turnover is reported.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..strategy.resolve import ResolvedStrategy, resolve
from ..strategy.schema import StrategyConfig
from . import metrics
from .results import BacktestResult, Trade


@dataclass
class _Pos:
    j: int
    shares: float
    entry: float
    entry_i: int
    stop: float | None
    target: float | None
    peak: float
    weight: float
    risk: float | None


@dataclass
class _Sim:
    cfg: StrategyConfig
    rs: ResolvedStrategy
    cost_rate: float = 0.0
    cash: float = 0.0
    positions: dict[int, _Pos] = field(default_factory=dict)
    trades: list[dict] = field(default_factory=list)
    traded_notional: float = 0.0


def _rebalance_dates(idx: pd.DatetimeIndex, freq: str) -> set:
    if freq == "daily":
        return set(idx)
    period = {"weekly": "W", "fortnightly": "W", "monthly": "M"}[freq]
    firsts = pd.Series(idx, index=idx).groupby(idx.to_period(period)).first().tolist()
    if freq == "fortnightly":
        firsts = firsts[::2]
    return set(firsts)


def _stop_target(cfg: StrategyConfig, entry: float, atr_v: float | None):
    sl, tp = cfg.stop_loss, cfg.take_profit
    stop = None
    if sl.type == "pct" and sl.value:
        stop = entry * (1 - sl.value)
    elif sl.type in ("atr", "trailing") and sl.mult and atr_v and not math.isnan(atr_v):
        stop = entry - sl.mult * atr_v
    risk = (entry - stop) if stop is not None else None
    target = None
    if tp.type == "pct" and tp.value:
        target = entry * (1 + tp.value)
    elif tp.type == "r_multiple" and tp.r and risk and risk > 0:
        target = entry + tp.r * risk
    return stop, target, risk


def run_backtest(config) -> BacktestResult:
    cfg = config if isinstance(config, StrategyConfig) else StrategyConfig(**config)
    rs = resolve(cfg)

    dates = rs.close_adj.index
    tickers = list(rs.close_adj.columns)
    col = {t: j for j, t in enumerate(tickers)}
    sectors = [rs.sectors.get(t, "Unknown") for t in tickers]

    def arr(df):
        return df.reindex(index=dates, columns=tickers).values if df is not None else None

    O, H, L, C = arr(rs.open_adj), arr(rs.high_adj), arr(rs.low_adj), arr(rs.close_adj)
    Cmark = rs.close_adj.reindex(index=dates, columns=tickers).ffill().values
    MASK = rs.entry_mask.reindex(index=dates, columns=tickers).fillna(False).values
    RANK = arr(rs.rank_score)
    ATR = arr(rs.atr_stop)
    VOL = arr(rs.ret_vol)
    ADTV = arr(rs.adtv_value)

    sim = _Sim(cfg=cfg, rs=rs, cash=cfg.capital)
    sim.cost_rate = (cfg.costs_bps.brokerage + cfg.costs_bps.stt + cfg.costs_bps.slippage) / 1e4
    cr = sim.cost_rate
    rebal = _rebalance_dates(dates, cfg.rebalance)

    nav_dates, nav_vals, exposure_vals = [], [], []
    pending: dict | None = None

    def close_pos(j: int, price: float, i: int, reason: str):
        pos = sim.positions.pop(j)
        proceeds = pos.shares * price * (1 - cr)
        sim.cash += proceeds
        sim.traded_notional += pos.shares * price
        net_entry = pos.entry * (1 + cr)
        net_exit = price * (1 - cr)
        ret_pct = net_exit / net_entry - 1.0 if net_entry > 0 else 0.0
        rmult = ((price - pos.entry) / pos.risk) if (pos.risk and pos.risk > 0) else None
        hold_days = int((dates[i] - dates[pos.entry_i]).days)
        sim.trades.append({
            "ticker": tickers[j], "entry_date": str(dates[pos.entry_i].date()),
            "entry": round(pos.entry, 4), "exit_date": str(dates[i].date()),
            "exit": round(price, 4), "return_pct": round(ret_pct, 6),
            "r_multiple": round(rmult, 3) if rmult is not None else None,
            "exit_reason": reason, "weight": round(pos.weight, 4), "holding_days": hold_days,
        })

    def open_pos(j: int, w: float, price: float, i: int, nav_now: float):
        if price is None or math.isnan(price) or price <= 0:
            return
        target_notional = w * nav_now
        adtv_v = ADTV[i, j] if ADTV is not None else float("nan")
        if not math.isnan(adtv_v) and adtv_v > 0:
            target_notional = min(target_notional, cfg.max_position_adtv_pct * adtv_v)
        shares = math.floor(target_notional / (price * (1 + cr)))
        max_aff = math.floor(sim.cash / (price * (1 + cr)))
        shares = min(shares, max_aff)
        if shares <= 0:
            return
        sim.cash -= shares * price * (1 + cr)
        sim.traded_notional += shares * price
        atr_v = ATR[i, j] if ATR is not None else None
        stop, target, risk = _stop_target(cfg, price, atr_v)
        sim.positions[j] = _Pos(j, shares, price, i, stop, target, price, w, risk)

    def check_exit(j: int, i: int):
        pos = sim.positions[j]
        o, hi, lo, c = O[i, j], H[i, j], L[i, j], C[i, j]
        if any(math.isnan(x) for x in (hi, lo, c)):
            return
        if cfg.stop_loss.type == "trailing" and ATR is not None:
            pos.peak = max(pos.peak, hi)
            av = ATR[i, j]
            if not math.isnan(av) and cfg.stop_loss.mult:
                pos.stop = max(pos.stop or -np.inf, pos.peak - cfg.stop_loss.mult * av)
        if pos.stop is not None and not math.isnan(pos.stop) and lo <= pos.stop:
            fill = pos.stop if (not math.isnan(o) and o >= pos.stop) else (o if not math.isnan(o) else pos.stop)
            return close_pos(j, fill, i, "stop")
        if pos.target is not None and not math.isnan(pos.target) and hi >= pos.target:
            fill = pos.target if (not math.isnan(o) and o <= pos.target) else (o if not math.isnan(o) else pos.target)
            return close_pos(j, fill, i, "target")
        if cfg.max_hold_days and (dates[i] - dates[pos.entry_i]).days >= cfg.max_hold_days:
            return close_pos(j, c, i, "time")

    def desired_set(i: int) -> tuple[list[int], dict[int, float]]:
        mrow, rrow = MASK[i], RANK[i]
        cands = [j for j in range(len(tickers))
                 if mrow[j] and not math.isnan(rrow[j])]
        cands.sort(key=lambda j: (rrow[j], tickers[j]), reverse=(cfg.rank_order == "desc"))
        chosen, sec_count = [], {}
        for j in cands:
            if cfg.sector_cap:
                s = sectors[j]
                if sec_count.get(s, 0) >= cfg.sector_cap:
                    continue
                sec_count[s] = sec_count.get(s, 0) + 1
            chosen.append(j)
            if len(chosen) >= cfg.n_holdings:
                break
        if cfg.weighting == "inverse_vol" and VOL is not None:
            inv = {}
            for j in chosen:
                v = VOL[i, j]
                inv[j] = (1.0 / v) if (not math.isnan(v) and v > 0) else 0.0
            tot = sum(inv.values()) or 1.0
            weights = {j: (inv[j] / tot if tot > 0 else 1.0 / len(chosen)) for j in chosen}
        else:
            weights = {j: 1.0 / cfg.n_holdings for j in chosen}
        return chosen, weights

    n = len(dates)
    for i in range(n):
        # 1) execute scheduled rebalance orders at today's open
        if pending is not None and pending["exec_i"] == i:
            desired = pending["desired"]
            for j in list(sim.positions):
                if j not in desired:
                    px = O[i, j]
                    close_pos(j, px if not math.isnan(px) else Cmark[i, j], i, "rebalance")
            nav_now = sim.cash + sum(p.shares * Cmark[i, p.j] for p in sim.positions.values())
            for j, w in pending["weights"].items():
                if j in sim.positions:
                    continue
                open_pos(j, w, O[i, j], i, nav_now)
            pending = None

        # 2) daily exit checks
        for j in list(sim.positions):
            check_exit(j, i)

        # 3) mark NAV at close
        invested = sum(p.shares * Cmark[i, p.j] for p in sim.positions.values())
        nav = sim.cash + invested
        nav_dates.append(dates[i]); nav_vals.append(nav)
        exposure_vals.append((invested / nav) if nav > 0 else 0.0)

        # 4) rebalance decision (data up to & incl today)
        if dates[i] in rebal:
            chosen, weights = desired_set(i)
            if cfg.entry_fill == "close":
                for j in list(sim.positions):
                    if j not in chosen:
                        close_pos(j, C[i, j] if not math.isnan(C[i, j]) else Cmark[i, j], i, "rebalance")
                nav_now = sim.cash + sum(p.shares * Cmark[i, p.j] for p in sim.positions.values())
                for j, w in weights.items():
                    if j not in sim.positions:
                        open_pos(j, w, C[i, j], i, nav_now)
            elif i + 1 < n:
                pending = {"exec_i": i + 1, "desired": set(chosen), "weights": weights}

    # liquidate residual positions at the final close (mark for reporting)
    last_i = n - 1
    for j in list(sim.positions):
        close_pos(j, Cmark[last_i, j], last_i, "end")

    nav = pd.Series(nav_vals, index=pd.DatetimeIndex(nav_dates))
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-6)
    avg_nav = float(nav.mean()) or cfg.capital
    annual_turnover = (sim.traded_notional / (2 * avg_nav)) / years if avg_nav else 0.0
    exposure = float(np.mean(exposure_vals)) if exposure_vals else 0.0

    bench = rs.benchmark.reindex(nav.index).ffill()
    summary = metrics.compute_summary(nav, sim.trades, bench, years, annual_turnover, exposure)

    dd = metrics.drawdown_series(nav)
    bench_nav = None
    if bench is not None and not bench.dropna().empty:
        b0 = bench.dropna().iloc[0]
        bench_nav = (bench / b0) * cfg.capital

    return BacktestResult(
        config_hash=cfg.hash(), name=cfg.name,
        period={"start": str(dates[0].date()), "end": str(dates[-1].date()),
                "years": round(years, 2), "n_days": int(n)},
        summary=summary,
        equity_curve=[[str(d.date()), round(float(v), 2)]
                      for d, v in nav.items() if math.isfinite(v)],
        drawdown_curve=[[str(d.date()), round(float(v), 5)]
                        for d, v in dd.items() if math.isfinite(v)],
        monthly_returns=metrics.monthly_returns(nav),
        benchmark_curve=([[str(d.date()), round(float(v), 2)]
                          for d, v in bench_nav.items() if math.isfinite(v)]
                         if bench_nav is not None else []),
        trades=[Trade(**t) for t in sim.trades],
        warnings=rs.warnings,
    )
