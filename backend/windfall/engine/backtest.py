"""Deterministic rebalance-and-hold simulator with daily, explicit exits.

Decision at the close of day t uses only data up to t; fills at the next bar's open (no look-ahead).
Between rebalances, stops / targets / trailing / time-exits are checked every day. Costs are
deducted on every entry and exit, and turnover is reported.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..strategy.resolve import ResolvedStrategy, resolve
from ..strategy.schema import Costs, StrategyConfig
from . import metrics
from .results import BacktestResult, Trade

# ── NSE equity-delivery cost model (Zerodha-class, ₹0 brokerage) ──────────────────────────────────
# Verified against the Zerodha/Groww brokerage calculators (iter-31). Side-aware fractions of
# turnover; DP is a FLAT per-sell fee (per scrip) — so it bites small capital hardest. No slippage:
# it's an assumption, not a fee — stress it via the cost-sensitivity multiplier instead.
_STT, _STAMP, _EXCH, _SEBI, _GST = 0.001, 0.00015, 0.0000297, 0.000001, 0.18
NSE_BUY_RATE = _STT + _STAMP + _EXCH + _SEBI + _GST * (_EXCH + _SEBI)   # ≈ 0.0011862  (11.9 bps)
NSE_SELL_RATE = _STT + _EXCH + _SEBI + _GST * (_EXCH + _SEBI)           # ≈ 0.0010362  (10.4 bps)
DP_FLAT = 15.93   # ₹/sell per scrip (Zerodha ₹13.5 + 18% GST)


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
    period = {"weekly": "W", "fortnightly": "W", "monthly": "M", "quarterly": "Q"}[freq]
    firsts = pd.Series(idx, index=idx).groupby(idx.to_period(period)).first().tolist()
    if freq == "fortnightly":
        firsts = firsts[::2]
    return set(firsts)


def _apply_max_weight(weights: dict[int, float], cap: float) -> dict[int, float]:
    """Cap any single name's weight at `cap`, redistributing the excess to uncapped names.

    Iterates because redistributing can push another name over the cap. If every name is at the
    cap (cap * n < total), weights simply sum to cap * n < 1 (the residual stays in cash).
    """
    w = dict(weights)
    for _ in range(len(w) + 1):
        over = {j: x for j, x in w.items() if x > cap + 1e-12}
        if not over:
            break
        excess = sum(x - cap for x in over.values())
        for j in over:
            w[j] = cap
        under = [j for j in w if w[j] < cap - 1e-12]
        if not under:
            break
        add = excess / len(under)
        for j in under:
            w[j] += add
    return w


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


def _warmup_calendar_days(cfg: StrategyConfig) -> int:
    """Calendar-day lead needed so the longest ROLLING feature is warm at the requested start.

    Scans every filter/rank expression (+ the regime MA) for windowed indicators
    (sma/ema/roc/rsi/atr/adx/adtv/vol_avg/dist_high/rel_strength + N) and returns ~2x the largest N
    in calendar days. Point-in-time factors (tl_*, fundamentals) need no warmup, so a pure-DVM
    strategy returns 0 and is untouched. Mirrors the lead signals_live already applies — without it,
    a short-window backtest of an sma200/roc125 strategy has NaN features -> empty early book.
    """
    exprs = list(cfg.entry_filters) + [cfg.rank_by] + [f.factor for f in cfg.rank_blend]
    max_n = 0
    for e in exprs:
        for _, n in re.findall(r"\b(sma|ema|roc|rsi|atr|adx|adtv|vol_avg|dist_high|rel_strength)(\d+)\b", e or ""):
            max_n = max(max_n, int(n))
    if cfg.regime_filter.enabled:
        max_n = max(max_n, cfg.regime_filter.ma_period)
    return (max_n * 2 + 30) if max_n else 0


def resolve_with_warmup(cfg: StrategyConfig):
    """Resolve over a warmup-padded window so rolling features are warm at cfg.start, returning the
    ResolvedStrategy. Exposed so a batch can resolve ONCE and reuse it across sim-side variants:
    n_holdings / rebalance / regime / exits / costs all live in the simulation, never in resolve().
    (Warmup bars warm sma200/roc125/regime but never trade.)"""
    pad = _warmup_calendar_days(cfg)
    resolve_cfg = cfg
    if pad and cfg.start:
        warm_start = str((pd.Timestamp(cfg.start) - pd.Timedelta(days=pad)).date())
        if warm_start < cfg.start:
            resolve_cfg = cfg.model_copy(update={"start": warm_start})
    return resolve(resolve_cfg)


def run_backtest(config, cost_mult: float = 1.0, rs=None) -> BacktestResult:
    cfg = config if isinstance(config, StrategyConfig) else StrategyConfig(**config)

    # `cfg` stays the USER's config (identity/hash/reporting). `rs` may be supplied pre-resolved so a
    # batch reuses one resolve across sim-side variants; when None we resolve with warmup as before.
    requested_start = cfg.start
    if rs is None:
        rs = resolve_with_warmup(cfg)

    dates = rs.close_adj.index
    # index of the first trading day on/after the user's requested start; warmup bars are < i0
    i0 = int(dates.searchsorted(pd.Timestamp(requested_start))) if requested_start else 0
    i0 = min(i0, len(dates))
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
    # Run-local (NOT rs.warnings — a batch shares rs across combos and would leak this between them).
    run_warnings: list[str] = []
    # cfg.costs_bps is INERT: adr-020 replaced it with the NSE delivery schedule below, but the field
    # still validates, so a config that sets it (e.g. zeros, expecting "costs OFF") silently runs at
    # full costs. Warn whenever it differs from the untouched default — that signals intent to use it.
    if cfg.costs_bps != Costs():
        run_warnings.append(
            "costs_bps is inert/deprecated — the engine charges the NSE delivery schedule "
            "(side-aware rates + flat DP, adr-020) regardless of it. To scale or disable costs, "
            "pass cost_mult (0.0 = gross) / use the cost-sensitivity endpoint.")
    # side-aware delivery costs, scaled by cost_mult (the cost-sensitivity card passes 0x/1x/2x)
    buy_rate = NSE_BUY_RATE * cost_mult
    sell_rate = NSE_SELL_RATE * cost_mult
    dp_flat = DP_FLAT * cost_mult
    sim.cost_rate = buy_rate
    rebal = _rebalance_dates(dates, cfg.rebalance)

    # Regime overlay: index value vs its moving average, aligned to the trading calendar.
    rf = cfg.regime_filter
    bench_val = rs.benchmark.reindex(dates).ffill().values
    bench_ma = rs.benchmark.reindex(dates).ffill().rolling(rf.ma_period,
                                                            min_periods=rf.ma_period).mean().values

    def regime_mult(i: int) -> float:
        if not rf.enabled:
            return 1.0
        bv, bm = bench_val[i], bench_ma[i]
        if math.isnan(bv) or math.isnan(bm):
            return 1.0  # insufficient history to judge regime — stay invested
        return 1.0 if bv >= bm else rf.below_exposure

    # Factor-timing overlay: self-time on the strategy's OWN equity vs its own MA. The timing signal
    # is the strategy's REFERENCE equity — the same strategy with factor-timing OFF (regime/costs/
    # everything else unchanged) — NOT the gated equity. Timing on the gated equity would be
    # self-referential (de-risking changes the curve that drives the next decision) and would not
    # match the offline PoC (which timed on the un-timed strategy curve). The reference curve is
    # itself look-ahead-free and truncation-invariant, and the gate reads it only through t-lag_days,
    # so the overlay inherits those properties. Mirrors regime_mult, but on the strategy's own equity
    # instead of the benchmark. Live-tractable: the signals engine produces the book daily, so the
    # reference equity is observable even while standing in cash.
    ft = cfg.factor_timing
    weekly_check = _rebalance_dates(dates, "weekly") if ft.check_weekly else set()
    ft_nav = ft_ma = None
    if ft.enabled:
        ref_cfg = cfg.model_copy(update={
            "factor_timing": ft.model_copy(update={"enabled": False, "check_weekly": False})})
        ref = run_backtest(ref_cfg, cost_mult=cost_mult, rs=rs)   # one reference sim (rs reused)
        ref_s = pd.Series({pd.Timestamp(d): float(v) for d, v in ref.equity_curve})
        ft_nav = ref_s.reindex(dates).ffill().values
        ft_ma = (pd.Series(ft_nav, index=dates)
                 .rolling(ft.ma_period, min_periods=ft.ma_period).mean().values)

    def factor_timing_mult(i: int) -> float:
        """Exposure multiplier: 1.0 while the strategy's reference equity is at/above its MA, else
        defensive. Reads the reference curve only at t-lag_days (no look-ahead). 1.0 until the MA is
        warm — you cannot time on equity you do not yet have (mirrors RegimeFilter's MA min_periods)."""
        if not ft.enabled:
            return 1.0
        k = i - ft.lag_days
        if k < 0:
            return 1.0
        nv, mv = ft_nav[k], ft_ma[k]
        if math.isnan(nv) or math.isnan(mv):
            return 1.0  # reference MA not warm yet -> stay invested
        return 1.0 if nv >= mv else (0.0 if ft.mode == "binary" else ft.below_exposure)

    def overlay_exposure(i: int) -> float:
        """Combined risk overlay (market-direction regime AND own-equity factor-timing): both must
        be 'on' for full exposure. Used by the weekly de-risk check to detect a fully-defensive flip."""
        return regime_mult(i) * factor_timing_mult(i)

    # Delisting terminal exit (survivorship-free runs): the last bar a name has a price is its
    # delisting date — a held position must be force-closed there at the last traded (adjusted)
    # price, never marked forward at a stale value. For live names this is just the final bar.
    delist_on = getattr(cfg, "data_source", "windfall") == "trendlyne"
    last_valid: list[int | None] = [None] * len(tickers)
    if delist_on:
        for j in range(len(tickers)):
            valid = np.where(~np.isnan(C[:, j]))[0]
            last_valid[j] = int(valid[-1]) if len(valid) else None

    nav_dates, nav_vals, exposure_vals = [], [], []
    pending: dict | None = None
    last_target: dict | None = None   # most recent monthly raw selection, for weekly re-engagement

    def close_pos(j: int, price: float, i: int, reason: str):
        pos = sim.positions.pop(j)
        proceeds = pos.shares * price * (1 - sell_rate) - dp_flat
        sim.cash += proceeds
        sim.traded_notional += pos.shares * price
        net_entry = pos.entry * (1 + buy_rate)
        net_exit = price * (1 - sell_rate) - (dp_flat / pos.shares if pos.shares else 0.0)
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
        shares = math.floor(target_notional / (price * (1 + buy_rate)))
        max_aff = math.floor(sim.cash / (price * (1 + buy_rate)))
        shares = min(shares, max_aff)
        if shares <= 0:
            return
        sim.cash -= shares * price * (1 + buy_rate)
        sim.traded_notional += shares * price
        atr_v = ATR[i, j] if ATR is not None else None
        stop, target, risk = _stop_target(cfg, price, atr_v)
        sim.positions[j] = _Pos(j, shares, price, i, stop, target, price, w, risk)

    def check_exit(j: int, i: int):
        pos = sim.positions[j]
        # Same-bar entry-stop guard (audit #99): a next-open fill lands in step 1 of bar i, then the
        # step-2 daily exit check runs on the SAME bar — a name could be entered at the open and stopped
        # out that very day (0-hold, entry-day intrabar noise). A position's first exit check is the bar
        # AFTER it opens; skip its entry bar. (Close-fill entries open after the step-2 check, so they
        # are unaffected either way.)
        if pos.entry_i == i:
            return
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

    def select_raw(i: int) -> tuple[list[int], dict[int, float]]:
        """The monthly selection: which names + their pre-overlay target weights. No risk overlay
        here — overlay is applied separately so the weekly check can re-time the SAME selection."""
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
        if not chosen:
            return [], {}
        if cfg.weighting == "inverse_vol" and VOL is not None:
            inv = {}
            for j in chosen:
                v = VOL[i, j]
                inv[j] = (1.0 / v) if (not math.isnan(v) and v > 0) else 0.0
            tot = sum(inv.values()) or 1.0
            weights = {j: (inv[j] / tot if tot > 0 else 1.0 / len(chosen)) for j in chosen}
        else:
            base = (1.0 / len(chosen)) if cfg.invest_fully else (1.0 / cfg.n_holdings)
            weights = {j: base for j in chosen}

        # Per-stock weight cap (Trendlyne "Max Weightage Per Stock"): cap + redistribute.
        if cfg.max_weight_per_stock and cfg.max_weight_per_stock > 0:
            weights = _apply_max_weight(weights, cfg.max_weight_per_stock)
        return chosen, weights

    def apply_overlay(weights: dict[int, float], i: int) -> dict[int, float]:
        """Scale a target book by the combined risk overlay. Returns {} when fully defensive."""
        if not weights:
            return {}
        # Regime overlay: binary -> go fully to cash; scale -> shrink target exposure.
        mult = regime_mult(i)
        if mult <= 0.0 and rf.mode == "binary":
            return {}
        if mult != 1.0:
            weights = {j: w * mult for j, w in weights.items()}
        # Factor-timing overlay (own-equity self-timing), applied on top of regime by the same rule.
        ftm = factor_timing_mult(i)
        if ftm <= 0.0 and ft.mode == "binary":
            return {}
        if ftm != 1.0:
            weights = {j: w * ftm for j, w in weights.items()}
        return weights

    def desired_set(i: int) -> tuple[list[int], dict[int, float]]:
        nonlocal last_target
        chosen, base = select_raw(i)
        if chosen:
            last_target = {"names": list(chosen), "weights": dict(base)}  # remember pre-overlay book
        ov = apply_overlay(base, i)
        if not ov:
            return [], {}
        return chosen, ov

    n = len(dates)
    # track rebalances that found zero eligible names -> book sits in cash. A run that is mostly empty
    # is almost always a data-coverage problem (a filter's factor has no data over part of the window,
    # e.g. tl_pledge before 2023 / DVM before 2016), not a real flat strategy. Surfaced as a warning so
    # it can't be mistaken for a genuine result (anti-gaslight: no silent empty book).
    n_rebals = empty_rebals = 0
    first_empty = last_empty = None
    for i in range(i0, n):  # skip warmup bars: features are warm by i0, the book starts flat there
        # 1) execute scheduled rebalance orders at today's open
        if pending is not None and pending["exec_i"] == i:
            desired = pending["desired"]
            exit_reason = pending.get("reason", "rebalance")
            for j in list(sim.positions):
                if j not in desired:
                    px = O[i, j]
                    close_pos(j, px if not math.isnan(px) else Cmark[i, j], i, exit_reason)
            nav_now = sim.cash + sum(p.shares * Cmark[i, p.j] for p in sim.positions.values())
            for j, w in pending["weights"].items():
                if j in sim.positions:
                    continue
                open_pos(j, w, O[i, j], i, nav_now)
            pending = None

        # 2) daily exit checks
        for j in list(sim.positions):
            check_exit(j, i)

        # 2b) delisting terminal exit — a held name that stops trading today exits at its last close
        if delist_on:
            for j in list(sim.positions):
                if last_valid[j] is not None and i == last_valid[j] and i < n - 1:
                    px = C[i, j]
                    close_pos(j, px if not math.isnan(px) else Cmark[i, j], i, "delisted")

        # 3) mark NAV at close
        invested = sum(p.shares * Cmark[i, p.j] for p in sim.positions.values())
        nav = sim.cash + invested
        nav_dates.append(dates[i]); nav_vals.append(nav)
        exposure_vals.append((invested / nav) if nav > 0 else 0.0)

        # 3c) weekly risk-overlay check: on a non-rebalance week, re-evaluate the combined overlay.
        # De-risk (always, when check_weekly): if it has flipped fully defensive while holding, schedule
        # a liquidation to cash. Re-engage (only when reengage_weekly): if it has flipped back on while
        # in cash, schedule a re-entry of the MOST RECENT MONTHLY selection (re-sized at the next fill).
        # The gate reads NAV through today (just appended). De-risk-only (reengage_weekly=False) is the
        # iter-16 behavior; bidirectional re-engagement (iter-17) is opt-in and catches the post-bottom
        # recoveries a monthly-only re-entry misses (adr-033).
        if (ft.check_weekly and dates[i] in weekly_check and dates[i] not in rebal
                and pending is None):
            ov = overlay_exposure(i)
            if sim.positions and ov <= 1e-9:                       # de-risk to cash
                if cfg.entry_fill == "close":
                    for j in list(sim.positions):
                        close_pos(j, C[i, j] if not math.isnan(C[i, j]) else Cmark[i, j], i,
                                  "overlay_exit")
                elif i + 1 < n:
                    pending = {"exec_i": i + 1, "desired": set(), "weights": {},
                               "reason": "overlay_exit"}
            elif ft.reengage_weekly and not sim.positions and ov > 1e-9 and last_target:
                rew = apply_overlay(last_target["weights"], i)    # re-time the last monthly book
                if rew:
                    if cfg.entry_fill == "close":
                        for j, w in rew.items():
                            open_pos(j, w, C[i, j], i, sim.cash)
                    elif i + 1 < n:
                        pending = {"exec_i": i + 1, "desired": set(rew.keys()),
                                   "weights": rew, "reason": "overlay_reenter"}

        # 4) rebalance decision (data up to & incl today)
        if dates[i] in rebal:
            chosen, weights = desired_set(i)
            n_rebals += 1
            if not chosen:                       # zero eligible names -> book parked in cash
                empty_rebals += 1
                if first_empty is None:
                    first_empty = dates[i]
                last_empty = dates[i]
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
    start_i = i0 if i0 < n else 0                 # traded window starts at i0 (post-warmup)
    years = max((dates[-1] - dates[start_i]).days / 365.25, 1e-6)
    avg_nav = float(nav.mean()) or cfg.capital
    annual_turnover = (sim.traded_notional / (2 * avg_nav)) / years if avg_nav else 0.0
    exposure = float(np.mean(exposure_vals)) if exposure_vals else 0.0

    # Transparency (audit #86): surface extreme one-day moves and multi-month price gaps on names WHILE
    # HELD. These are usually REAL (special auctions like Elcid, multi-month suspensions like Indosolar/
    # WAAREEINDO), but a silent 40% jump or a 3-year gap marked forward is indistinguishable from a data
    # error unless it is flagged. Scans each trade's held window on the adjusted close.
    big_moves, susp_gaps = [], []
    for t in sim.trades:
        tk = t["ticker"]
        if tk not in rs.close_adj.columns:
            continue
        s = rs.close_adj.loc[t["entry_date"]:t["exit_date"], tk].dropna()
        if len(s) < 2:
            continue
        rr = s.pct_change().abs()
        if float(rr.max()) >= 0.40:
            big_moves.append(f"{tk} {float(rr.max())*100:.0f}% on {rr.idxmax().date()}")
        gap = s.index.to_series().diff().dt.days.max()
        if gap and int(gap) >= 60:
            susp_gaps.append(f"{tk} {int(gap)}d")
    if big_moves:
        rs.warnings.append(
            "held names had >40% one-day moves (verify these are real events — special auctions, "
            "resumptions — not price errors): " + ", ".join(big_moves[:8])
            + (f" +{len(big_moves) - 8} more" if len(big_moves) > 8 else ""))
    if susp_gaps:
        rs.warnings.append(
            "held names had multi-month price gaps (suspension/illiquidity — marked forward at the last "
            "close, so interim P&L is held flat): " + ", ".join(susp_gaps[:8])
            + (f" +{len(susp_gaps) - 8} more" if len(susp_gaps) > 8 else ""))

    if empty_rebals and n_rebals:
        rs.warnings.append(
            f"{empty_rebals}/{n_rebals} rebalances had NO eligible names — the book was in cash on "
            f"those dates ({str(first_empty.date())} … {str(last_empty.date())}). This usually means a "
            f"filter references a factor with no data over part of the window (e.g. tl_pledge before "
            f"2023, DVM before 2016); the return for those periods is cash, not the strategy.")

    bench = rs.benchmark.reindex(nav.index).ffill()
    summary = metrics.compute_summary(nav, sim.trades, bench, years, annual_turnover, exposure)

    dd = metrics.drawdown_series(nav)
    bench_nav = None
    if bench is not None and not bench.dropna().empty:
        b0 = bench.dropna().iloc[0]
        bench_nav = (bench / b0) * cfg.capital

    return BacktestResult(
        config_hash=cfg.hash(), name=cfg.name,
        period={"start": str(dates[start_i].date()), "end": str(dates[-1].date()),
                "years": round(years, 2), "n_days": int(n - start_i)},
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
        # dedupe: a factor-timing run shares `rs` with its reference sim, which can append an
        # identical empty-rebals warning — collapse to unique, order-preserving.
        warnings=list(dict.fromkeys(rs.warnings + run_warnings)),
    )
