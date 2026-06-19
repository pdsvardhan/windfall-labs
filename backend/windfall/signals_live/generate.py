"""Run a saved strategy on the latest data -> today's buy / hold / sell list.

Buy = newly entered the top-N this rebalance; Hold = was in last rebalance and still in;
Sell = dropped out of the top-N. Entry zone follows the methodology's anti-chase rule.
"""
from __future__ import annotations

import csv
import io
import math

from .. import signals as ind
from ..engine.backtest import _stop_target
from ..strategy.resolve import ResolvedStrategy, resolve
from ..strategy.schema import StrategyConfig

_STEP = {"daily": 1, "weekly": 5, "fortnightly": 10, "monthly": 21}


def _select(rs: ResolvedStrategy, i: int, cfg: StrategyConfig) -> dict[str, tuple[float, float]]:
    tickers = list(rs.close_adj.columns)
    mrow = rs.entry_mask.reindex(columns=tickers).iloc[i].values
    rrow = rs.rank_score.reindex(columns=tickers).iloc[i].values
    sectors = [rs.sectors.get(t, "Unknown") for t in tickers]
    cands = [j for j in range(len(tickers)) if bool(mrow[j]) and not math.isnan(rrow[j])]
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
    w = 1.0 / cfg.n_holdings
    return {tickers[j]: (float(rrow[j]), w) for j in chosen}


def generate_signals(config) -> dict:
    cfg = config if isinstance(config, StrategyConfig) else StrategyConfig(**config)
    rs = resolve(cfg)
    dates = rs.close_adj.index
    if len(dates) < 60:
        return {"as_of": None, "signals": [], "warnings": rs.warnings + ["insufficient history"]}

    last_i = len(dates) - 1
    prev_i = max(0, last_i - _STEP[cfg.rebalance])
    today = _select(rs, last_i, cfg)
    prev = _select(rs, prev_i, cfg)
    today_set, prev_set = set(today), set(prev)

    sma50 = ind.sma(rs.close_adj, 50).iloc[last_i]
    rsi14 = ind.rsi(rs.close_adj, 14).iloc[last_i]
    atr14 = (rs.atr_stop if rs.atr_stop is not None
             else ind.atr(rs.high_adj, rs.low_adj, rs.close_adj, 14)).iloc[last_i]
    close = rs.close_adj.iloc[last_i]

    sigs = []
    for ticker, (rank, weight) in sorted(today.items(), key=lambda kv: -kv[1][0]):
        entry = float(close.get(ticker, float("nan")))
        if math.isnan(entry):
            continue
        atr_v = float(atr14.get(ticker, float("nan")))
        stop, target, _risk = _stop_target(cfg, entry, atr_v)
        ext = entry / float(sma50.get(ticker, entry)) - 1.0 if sma50.get(ticker) else 0.0
        r = float(rsi14.get(ticker, float("nan")))
        zone = "buy-now" if (ext <= 0.20 and (math.isnan(r) or r <= 68)) else "buy-on-dip"
        sigs.append({
            "ticker": ticker, "action": "hold" if ticker in prev_set else "buy",
            "rank_value": round(rank, 4), "weight": round(weight, 4),
            "last_close": round(entry, 2), "entry_zone": zone,
            "stop": round(stop, 2) if stop else None,
            "target": round(target, 2) if target else None,
            "ext_above_50dma": round(ext, 4), "rsi14": round(r, 1) if not math.isnan(r) else None,
        })
    for ticker in sorted(prev_set - today_set):
        entry = float(close.get(ticker, float("nan")))
        sigs.append({"ticker": ticker, "action": "sell", "weight": 0.0,
                     "last_close": round(entry, 2) if not math.isnan(entry) else None,
                     "note": "dropped out of top-N at this rebalance"})
    return {"as_of": str(dates[last_i].date()), "strategy": cfg.name,
            "n_holdings": cfg.n_holdings, "signals": sigs, "warnings": rs.warnings}


def signals_to_csv(run: dict) -> str:
    """Serialize a signal run's list to CSV text (the exportable order list)."""
    cols = ["ticker", "action", "rank_value", "weight", "last_close", "entry_zone",
            "stop", "target", "ext_above_50dma", "rsi14", "note"]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for s in run.get("signals", []):
        writer.writerow(s)
    return out.getvalue()
