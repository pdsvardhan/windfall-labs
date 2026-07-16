"""Resolve a declarative StrategyConfig into the concrete panels the engine consumes.

Filter/rank expressions reference named features (close, sma50, roc21, rsi14, adtv_cr, ...).
We build only the features that appear in the config, then evaluate each expression columnwise
into a boolean (filters) or numeric (rank) wide panel. NaN never passes a filter.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import signals as ind
from ..data import fundamentals as fund
from ..data import store
from ..data import trendlyne_store as ts
from ..data.universe import benchmark_ticker
from .safe_eval import SafeEvalError, feature_names, safe_eval
from .schema import StrategyConfig

_PARAM = re.compile(r"^(sma|ema|roc|rsi|atr|adx|adtv|vol_avg|dist_high|rel_strength)(\d+)$")
_BASE = {"close", "open", "high", "low", "volume", "adj_close", "price"}
_SPECIAL = {"adtv_cr", "macd", "macd_signal", "macd_hist", "peg"}
# Fundamental features from the Trendlyne snapshot (point-in-time; NaN before the snapshot date).
_FUND = set(fund.NUMERIC_FIELDS) | {"pe_to_sector"}
# Raw fundamentals that gain real history from the screener store (roe/roa/opm/np_qtr_yoy + computed
# valuation pe/pb): 120d-lagged point-in-time over ~2006->present, not snapshot-gated.
_HIST_FUND = set(fund.SCREENER_HISTORY_FIELDS)
# Trendlyne full-history features (data_source="trendlyne"): the platform's own daily DVM scores
# and valuation multiples (point-in-time by construction), plus result-lag-gated raw fundamentals.
_TL_DAILY = {"tl_durability", "tl_valuation", "tl_momentum", "tl_pe", "tl_peg", "tl_pbv"}
_TL_LAGGED = {"tl_roe", "tl_roce", "tl_de", "tl_opm", "tl_eps",
              # iter-32 curated factor library (result-lag-gated annual/quarterly, no look-ahead)
              "tl_roic", "tl_eyield", "tl_ps", "tl_current_ratio", "tl_quick_ratio",
              "tl_int_cover", "tl_cfo", "tl_piotroski", "tl_np_growth", "tl_rev_growth"}
_TL_SHARE = {"tl_pledge", "tl_fii", "tl_dii"}   # quarterly shareholding %, result-lag-gated
_TL_MCAP = {"mcap"}                              # point-in-time survivorship-free market cap (Rs cr)
_TL_FEATURES = _TL_DAILY | _TL_LAGGED | _TL_SHARE | _TL_MCAP


@dataclass
class ResolvedStrategy:
    config: StrategyConfig
    tickers: list[str]
    entry_mask: pd.DataFrame          # date x ticker, bool — passes all entry+universe filters
    rank_score: pd.DataFrame          # date x ticker, numeric — ranking metric
    open_adj: pd.DataFrame            # adjusted open (fills)
    close_adj: pd.DataFrame           # adjusted close (marking)
    high_adj: pd.DataFrame
    low_adj: pd.DataFrame
    atr_stop: pd.DataFrame | None     # ATR panel for stop sizing, if needed
    ret_vol: pd.DataFrame             # rolling return volatility (inverse-vol weighting)
    adtv_value: pd.DataFrame          # ADTV in rupees (sizing cap)
    sectors: dict[str, str]
    benchmark: pd.Series
    warnings: list[str] = field(default_factory=list)


def _trading_dates(close: pd.DataFrame) -> pd.DatetimeIndex:
    return close.index


def _percentile_blend(factors, mask, eval_expr, idx, cols, warnings) -> pd.DataFrame | None:
    """Cross-sectional percentile blend over the eligible set, per rebalance date.

    For each factor: evaluate -> restrict to eligible cells (mask) -> percentile-rank across
    tickers within each date (inverting for 'asc' factors) -> multiply by weight. Sum the
    (pct * weight) contributions and divide by the per-cell sum of weights that actually had a
    value, so a factor that is NaN for a name (e.g. a fundamental before its snapshot) drops out
    and the remaining weights renormalize. Returns a date x ticker score panel (higher = better),
    NaN where ineligible or where no factor had data.
    """
    blended: pd.DataFrame | None = None   # running sum of pct*weight over available factors
    wsum: pd.DataFrame | None = None      # running sum of weights over available factors (per cell)
    for rf in factors:
        panel = eval_expr(rf.factor)
        if panel is None:
            warnings.append(f"rank_blend factor '{rf.factor}' unresolved — dropped from blend")
            continue
        vals = panel.reindex(index=idx, columns=cols).where(mask)   # NaN where not eligible
        if rf.order == "asc":
            vals = -vals
        pct = vals.rank(axis=1, pct=True)                           # percentile within eligible non-NaN
        contrib = (pct * rf.weight).fillna(0.0)
        present = pct.notna().astype(float) * rf.weight
        blended = contrib if blended is None else blended.add(contrib)
        wsum = present if wsum is None else wsum.add(present)
        if float(pct.notna().to_numpy().mean()) == 0.0:
            warnings.append(
                f"rank_blend factor '{rf.factor}' has no data in this window — excluded from the "
                f"blend here (e.g. a fundamental before its first snapshot).")
    if blended is None or wsum is None:
        return None
    return blended.divide(wsum.replace(0.0, np.nan)).where(mask)    # weighted-mean percentile


def resolve(cfg: StrategyConfig) -> ResolvedStrategy:
    warnings: list[str] = []
    index = cfg.universe.index
    use_tl = cfg.data_source == "trendlyne"
    tv: pd.DataFrame | None = None              # daily rupee traded value (trendlyne ADTV source)
    membership_mask: pd.DataFrame | None = None  # point-in-time Rs500cr eligibility (survivorship-free)

    if use_tl:
        if not ts.available():
            raise ValueError("data_source='trendlyne' but trendlyne.duckdb is not present.")
        end = cfg.end or str(pd.Timestamp.today().date())
        live = cfg.end is None  # live signals: extend prices with the latest Bhavcopy EOD we hold
        tickers = ts.universe_over_window(cfg.start, end)
        if not tickers:
            raise ValueError("Empty survivorship-free universe for this window.")
        close = ts.adjusted_close_panel(tickers, cfg.start, cfg.end, "close", extend_live=live)
        if close.empty:
            raise ValueError("No Trendlyne price data for the resolved universe.")
        tickers = list(close.columns)
        open_ = ts.adjusted_close_panel(tickers, cfg.start, cfg.end, "open", extend_live=live).reindex(
            index=close.index, columns=tickers)
        high = ts.adjusted_close_panel(tickers, cfg.start, cfg.end, "high", extend_live=live).reindex(
            index=close.index, columns=tickers)
        low = ts.adjusted_close_panel(tickers, cfg.start, cfg.end, "low", extend_live=live).reindex(
            index=close.index, columns=tickers)
        tv = ts.traded_value_panel(tickers, cfg.start, cfg.end).reindex(
            index=close.index, columns=tickers)
        raw_close, raw_vol = close, None        # traded value handled via tv; ADTV is split-invariant
        bench_raw = ts.benchmark_series(cfg.benchmark, cfg.start, cfg.end)
        benchmark = bench_raw.reindex(close.index).ffill()
        if benchmark.dropna().empty:
            benchmark = close.mean(axis=1)
            warnings.append("benchmark index not in trendlyne — equal-weight average fallback.")
        elif not bench_raw.empty and bench_raw.index.min() > close.index.min():
            # e.g. Nifty Smallcap 250 begins 2019-01-14 (audit #87): dates before the index's first bar
            # have nothing to compare against, so regime overlay + active-return are blind there.
            warnings.append(
                f"benchmark '{cfg.benchmark}' history starts {bench_raw.index.min().date()}; dates before "
                f"it have no index to compare against, so regime/active-return are blind over that early "
                f"window (source a longer index history to extend it).")
        membership_mask = ts.membership_panel(tickers, close.index)
        n_uncertain = len(set(tickers) & ts.ca_uncertain_symbols())
        warnings.append(
            f"survivorship-free Trendlyne layer: {len(tickers)} names ever >Rs{int(ts.MCAP_FLOOR_CR)}cr "
            f"in-window (live + delisted, blow-ups included); membership is point-in-time; prices are "
            f"split/bonus-adjusted (delisted via the iter-28 CA master).")
        if n_uncertain:
            warnings.append(
                f"data-quality: {n_uncertain} delisted name(s) in the universe have an unconfirmed "
                f"corporate action (ca_uncertain) — included to avoid survivorship bias, but their "
                f"split adjustment may be imperfect.")
    else:
        members = store.universe_tickers(index)
        have = set(store.available_tickers())
        tickers = [t for t in members if t in have] or [t for t in have if t.endswith(".NS")]
        close = store.price_panel("close", tickers, cfg.start, cfg.end, adjusted=True)
        open_ = store.price_panel("open", tickers, cfg.start, cfg.end, adjusted=True)
        high = store.price_panel("high", tickers, cfg.start, cfg.end, adjusted=True)
        low = store.price_panel("low", tickers, cfg.start, cfg.end, adjusted=True)
        if close.empty:
            raise ValueError("No price data for the resolved universe — load data first.")
        tickers = list(close.columns)
        raw_close = store.price_panel("close", tickers, cfg.start, cfg.end, adjusted=False)
        raw_vol = store.price_panel("volume", tickers, cfg.start, cfg.end, adjusted=False)
        bt = benchmark_ticker(cfg.benchmark)
        bench_panel = store.price_panel("close", [bt], cfg.start, cfg.end, adjusted=True)
        if not bench_panel.empty and bt in bench_panel.columns:
            benchmark = bench_panel[bt]
        else:
            benchmark = close.mean(axis=1)
            warnings.append(
                f"benchmark '{cfg.benchmark}' ({bt}) not loaded — falling back to an equal-weight "
                f"universe average; benchmark_cagr/active_return are NOT the real index.")

    sectors_map = ts.sector_map() if use_tl else store.sector_map(index)
    cache: dict[str, pd.DataFrame] = {}

    def feat(name: str) -> pd.DataFrame:
        if name in cache:
            return cache[name]
        df: pd.DataFrame
        if name in ("close", "adj_close", "price"):
            df = close
        elif name == "open":
            df = open_
        elif name == "high":
            df = high
        elif name == "low":
            df = low
        elif name == "volume":
            df = (tv / close) if use_tl else raw_vol      # trendlyne: approx shares from traded value
        elif name == "adtv_cr":
            df = (tv.rolling(20, min_periods=5).mean() / 1e7) if use_tl \
                else ind.adtv(raw_close, raw_vol, 20) / 1e7
        elif name in _TL_FEATURES:
            if not use_tl:
                warnings.append(f"'{name}' needs data_source='trendlyne' — feature is all-NaN here")
                df = None
            elif name in ("tl_durability", "tl_valuation", "tl_momentum"):
                df = ts.dvm_panel(name, tickers).reindex(index=close.index, columns=tickers).ffill()
            elif name in ("tl_pe", "tl_peg", "tl_pbv"):
                df = ts.valuation_panel(name, tickers).reindex(index=close.index, columns=tickers).ffill()
            elif name in _TL_MCAP:  # point-in-time survivorship-free market cap (Rs cr)
                df = ts.mcap_panel(tickers, close.index).reindex(index=close.index, columns=tickers)
            elif name in _TL_SHARE:  # quarterly shareholding %, result-lag-gated (no look-ahead)
                df = ts.shareholding_panel(name, tickers, close.index).reindex(columns=tickers)
            else:  # result-lag-gated raw annual/quarterly fundamentals (no look-ahead per adr-016)
                df = ts.raw_fundamental_panel(name, tickers, close.index).reindex(columns=tickers)
        elif name == "macd":
            df = ind.macd(close)[0]
        elif name == "macd_signal":
            df = ind.macd(close)[1]
        elif name == "macd_hist":
            df = ind.macd(close)[2]
        elif name == "pe_to_sector":
            # sector_pe is snapshot-only (no historical sector-PE feed), so pe_to_sector is all-NaN
            # before the snapshot and a backtest using it trades nothing over history (audit #95).
            # Honest surface here rather than a silent empty book; use it on /signals or rank on tl_pe/pe.
            warnings.append(
                "pe_to_sector uses sector_pe, which is snapshot-only (no historical sector-PE data) — it "
                "is NaN before the snapshot, so a historical backtest holds nothing. Use it on live "
                "signals, or rank on tl_pe / pe instead.")
            df = feat("pe") / feat("sector_pe").replace(0.0, np.nan)
        elif name == "peg":
            # P/E ÷ EPS-growth% — growth-adjusted cheapness, guarded to profitable & growing names.
            # eps_growth is snapshot-only, so PEG contributes to valuation only from the snapshot
            # forward (NaN before — same gating as the other snapshot-only fundamentals).
            pe_, g = feat("pe"), feat("eps_growth")
            df = pe_.where(pe_ > 0) / g.where(g > 0)
        elif name == "pe":
            # Historical PE = price / EPS (loss-makers eps<=0 -> NaN). Today's price x the most-recent
            # KNOWN (120d-lagged) annual EPS, so no look-ahead. Snapshot governs the present.
            snap = fund.fundamental_panel("pe", close.index, tickers)
            eps_h = fund.screener_history_panel("eps", close.index, tickers)
            if eps_h is None:
                df = snap
            else:
                df = snap.combine_first(close / eps_h.where(eps_h > 0))
        elif name == "pb":
            # Historical PB via the identity PB = PE * ROE (shares = NP_owner/EPS), both 120d-lagged;
            # guard PB>0 to drop negative-net-worth cases. Snapshot governs the present.
            snap = fund.fundamental_panel("pb", close.index, tickers)
            eps_h = fund.screener_history_panel("eps", close.index, tickers)
            roe_h = fund.screener_history_panel("roe", close.index, tickers)
            if eps_h is None or roe_h is None:
                df = snap
            else:
                pb_h = (close / eps_h.where(eps_h > 0)) * roe_h / 100.0
                df = snap.combine_first(pb_h.where(pb_h > 0))
        elif name in fund.NUMERIC_FIELDS:
            snap = fund.fundamental_panel(name, close.index, tickers)
            # durability inputs (roe/roa/opm/np_qtr_yoy) gain real history from the screener store.
            # combine_first keeps the snapshot where it has a value (from its date forward) and uses
            # the 120d-lagged screener history for the past — present from snapshot, history from
            # screener, with no look-ahead. Other fundamentals (None) stay snapshot-only.
            hist = fund.screener_history_panel(name, close.index, tickers)
            df = snap if hist is None else snap.combine_first(hist)
        else:
            m = _PARAM.match(name)
            if not m:
                raise KeyError(name)
            kind, n_s = m.group(1), int(m.group(2))
            if kind == "sma":
                df = ind.sma(close, n_s)
            elif kind == "ema":
                df = ind.ema(close, n_s)
            elif kind == "roc":
                df = ind.roc(close, n_s)
            elif kind == "rsi":
                df = ind.rsi(close, n_s)
            elif kind == "atr":
                df = ind.atr(high, low, close, n_s)
            elif kind == "adx":
                df = ind.adx(high, low, close, n_s)
            elif kind == "adtv":
                df = tv.rolling(n_s, min_periods=max(2, n_s // 2)).mean() if use_tl \
                    else ind.adtv(raw_close, raw_vol, n_s)
            elif kind == "vol_avg":
                df = (tv / close).rolling(n_s, min_periods=max(2, n_s // 2)).mean() if use_tl \
                    else ind.volume_avg(raw_vol, n_s)
            elif kind == "dist_high":
                df = ind.dist_from_high(close, n_s)
            elif kind == "rel_strength":
                df = ind.relative_strength(close, benchmark, n_s)
            else:  # pragma: no cover
                raise KeyError(name)
        if df is None:  # a score with no usable inputs -> an all-NaN panel (never passes a filter)
            df = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
        cache[name] = df
        return df

    def eval_expr(expr: str) -> pd.DataFrame | None:
        ns: dict[str, pd.DataFrame] = {}
        for tok in feature_names(expr):
            if not (tok in _BASE or tok in _SPECIAL or tok in _FUND
                    or tok in _TL_FEATURES or _PARAM.match(tok)):
                warnings.append(f"unknown feature '{tok}' in '{expr}' — filter skipped")
                return None
            ns[tok] = feat(tok)
        try:
            return safe_eval(expr, ns)
        except SafeEvalError as exc:
            warnings.append(f"rejected expression '{expr}': {exc} — filter skipped")
            return None
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"could not evaluate '{expr}': {exc!r} — skipped")
            return None

    # Universe + entry filters → combined boolean mask.
    mask = pd.DataFrame(True, index=close.index, columns=close.columns)
    for expr in list(cfg.universe.filters) + list(cfg.entry_filters):
        res = eval_expr(expr)
        if res is None:
            continue
        res = res.reindex(index=close.index, columns=close.columns)
        mask &= res.fillna(False).astype(bool)

    # Point-in-time survivorship-free membership gate (trendlyne): a name is eligible only on the
    # dates its market cap actually exceeded the floor — dead names drop out when they shrink/delist.
    if use_tl and membership_mask is not None:
        mm = membership_mask.reindex(index=close.index, columns=close.columns).fillna(False).astype(bool)
        mask &= mm
        warnings.append("universe gated to point-in-time Rs500cr membership (survivorship-free).")

    # Sector exclusion (e.g. the methodology's "exclude Banking & Finance").
    if cfg.universe.exclude_sectors:
        sect = fund.fundamentals_sector_map()
        excl = [s.strip().lower() for s in cfg.universe.exclude_sectors]
        drop = [t for t in close.columns
                if any(e in (sect.get(t) or sectors_map.get(t) or "").lower() for e in excl)]
        if drop:
            mask[drop] = False
            warnings.append(f"excluded {len(drop)} names in sectors {cfg.universe.exclude_sectors}")

    # Honesty: which fundamentals are screener-history-backed (120d-lagged, real history) vs
    # snapshot-only (NaN before the single Trendlyne snapshot).
    blend_exprs = [rf.factor for rf in cfg.rank_blend]
    all_exprs = (list(cfg.universe.filters) + list(cfg.entry_filters) + blend_exprs
                 + ([cfg.rank_by] if not cfg.rank_blend else []))
    used_fund = {t for e in all_exprs for t in feature_names(e) if t in _FUND}
    if used_fund:
        sccov = fund.screener_coverage()
        hist_used = sorted(t for t in used_fund if t in _HIST_FUND)
        snap_used = sorted(t for t in used_fund if t not in _HIST_FUND)
        if hist_used and sccov.get("available"):
            warnings.append(
                f"fundamentals {hist_used} are screener-history-backed "
                f"({sccov['tickers']} names from {sccov['history_from']}, {fund.PIT_LAG_DAYS}d-lagged); "
                f"the live snapshot governs the present, while piotroski/pledge/sector-PE and "
                f"eps_growth remain snapshot-only.")
        snaps = fund.snapshots()
        if snap_used and snaps:
            warnings.append(
                f"snapshot-only fundamentals {snap_used} come from Trendlyne snapshots {snaps} and are "
                f"NaN before the first snapshot, so they apply to live signals / dates on-or-after the "
                f"snapshot, not historical backtests.")
        elif snap_used:
            warnings.append(
                f"snapshot-only fundamentals {snap_used} but no fundamentals snapshot is loaded.")

    # Rank score — a single expression, or a multi-factor cross-sectional percentile blend.
    if cfg.rank_blend:
        rank = _percentile_blend(cfg.rank_blend, mask, eval_expr,
                                 close.index, close.columns, warnings)
        if rank is None:
            warnings.append("rank_blend produced no usable factors — defaulting to roc21")
            rank = feat("roc21").reindex(index=close.index, columns=close.columns)
    else:
        rank = eval_expr(cfg.rank_by)
        if rank is None:
            warnings.append(f"rank_by '{cfg.rank_by}' unresolved — defaulting to roc21")
            rank = feat("roc21")
        rank = rank.reindex(index=close.index, columns=close.columns)

    atr_stop = None
    if cfg.stop_loss.type in ("atr", "trailing"):
        atr_stop = ind.atr(high, low, close, cfg.stop_loss.atr_period)

    ret = close.pct_change()
    ret_vol = ret.rolling(20, min_periods=10).std()
    adtv_value = (tv.rolling(20, min_periods=5).mean() if use_tl
                  else ind.adtv(raw_close, raw_vol, 20))

    return ResolvedStrategy(
        config=cfg, tickers=tickers, entry_mask=mask, rank_score=rank,
        open_adj=open_, close_adj=close, high_adj=high, low_adj=low,
        atr_stop=atr_stop, ret_vol=ret_vol, adtv_value=adtv_value,
        sectors=sectors_map, benchmark=benchmark, warnings=warnings,
    )
