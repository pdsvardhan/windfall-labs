"""Rolling walk-forward: optimize in-sample, test out-of-sample, roll, report degradation."""
from __future__ import annotations

import datetime as dt

from ..engine.backtest import run_backtest
from ..strategy.schema import StrategyConfig
from .sweep import apply_overrides, sweep


def _add_years(d: dt.date, years: float) -> dt.date:
    return d + dt.timedelta(days=int(years * 365.25))


def walk_forward(
    base_config: dict, grid: dict[str, list], metric: str = "sharpe",
    is_years: float = 3.0, oos_years: float = 1.0,
) -> dict:
    """Roll [IS optimize -> OOS test] windows across the configured date range."""
    base = StrategyConfig(**base_config).model_dump()
    start = dt.date.fromisoformat(base["start"])
    end = dt.date.fromisoformat(base["end"]) if base.get("end") else dt.date.today()

    windows = []
    is_start = start
    while True:
        is_end = _add_years(is_start, is_years)
        oos_end = _add_years(is_end, oos_years)
        if is_end >= end:
            break
        oos_end = min(oos_end, end)

        is_cfg = apply_overrides(base, {"start": is_start.isoformat(), "end": is_end.isoformat()})
        opt = sweep(is_cfg, grid, metric=metric)
        best = opt["ranked"][0] if opt["ranked"] else {"overrides": {}, "value": 0.0}
        best_overrides = best.get("overrides", {})

        oos_cfg = apply_overrides(base, {**best_overrides,
                                         "start": is_end.isoformat(), "end": oos_end.isoformat()})
        oos_res = run_backtest(oos_cfg)
        oos_summ = oos_res.summary.model_dump()

        is_val = best.get("value", 0.0)
        oos_val = oos_summ.get(metric, 0.0)
        windows.append({
            "is_window": [is_start.isoformat(), is_end.isoformat()],
            "oos_window": [is_end.isoformat(), oos_end.isoformat()],
            "best_overrides": best_overrides,
            "is_metric": round(float(is_val), 4),
            "oos_metric": round(float(oos_val), 4),
            "oos_summary": oos_summ,
        })
        is_start = _add_years(is_start, oos_years)  # roll forward by the OOS length

    is_avg = _avg([w["is_metric"] for w in windows])
    oos_avg = _avg([w["oos_metric"] for w in windows])
    degradation = (oos_avg - is_avg)
    verdict = "robust" if (is_avg <= 0 or oos_avg / is_avg >= 0.5) else "likely-curve-fit"
    return {
        "metric": metric, "is_years": is_years, "oos_years": oos_years,
        "n_windows": len(windows), "windows": windows,
        "is_avg": round(is_avg, 4), "oos_avg": round(oos_avg, 4),
        "degradation": round(degradation, 4),
        "oos_to_is_ratio": round((oos_avg / is_avg), 3) if is_avg else None,
        "verdict": verdict,
    }


def _avg(xs: list[float]) -> float:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0
