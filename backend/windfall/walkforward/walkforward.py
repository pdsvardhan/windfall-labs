"""Rolling walk-forward: optimize in-sample, test out-of-sample, roll, report degradation."""
from __future__ import annotations

import datetime as dt

from ..engine.backtest import run_backtest
from ..strategy.schema import StrategyConfig
from .sweep import apply_overrides, sweep


# The trailing out-of-sample fold is clipped to the configured end date (`oos_end = min(oos_end,
# end)`), so it can be a stub — measured as short as 8 days — while the averages weight it exactly
# as heavily as a full year. A handful of days of noise then moves the robustness verdict for the
# whole strategy. A fold shorter than one quarter is not evidence; it is reported but excluded from
# the averages (iter-172, to-do #251).
_MIN_OOS_DAYS = 90


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
        oos_days = (oos_end - is_end).days
        windows.append({
            "is_window": [is_start.isoformat(), is_end.isoformat()],
            "oos_window": [is_end.isoformat(), oos_end.isoformat()],
            "best_overrides": best_overrides,
            "is_metric": round(float(is_val), 4),
            "oos_metric": round(float(oos_val), 4),
            "oos_days": oos_days,
            # Only the trailing fold can be clipped, but flag structurally rather than positionally.
            "truncated": oos_days < _MIN_OOS_DAYS,
            "oos_summary": oos_summ,
        })
        is_start = _add_years(is_start, oos_years)  # roll forward by the OOS length

    warnings: list[str] = []
    scored = [w for w in windows if not w["truncated"]]
    dropped = [w for w in windows if w["truncated"]]
    if dropped and scored:
        warnings.append(
            f"excluded {len(dropped)} out-of-sample fold(s) shorter than {_MIN_OOS_DAYS} days "
            f"({', '.join(str(w['oos_days']) + 'd' for w in dropped)}) from the averages — a stub "
            f"window is noise, and weighting it like a full fold moves the verdict on a few days "
            f"of data. They are still listed in `windows`.")
    elif dropped and not scored:
        # Every fold is a stub: the window is too short to walk forward at all. Averaging them is
        # meaningless, but returning nothing hides that — so score them and say so loudly.
        scored = windows
        warnings.append(
            f"EVERY out-of-sample fold is shorter than {_MIN_OOS_DAYS} days — this date range is "
            f"too short for is_years={is_years}/oos_years={oos_years}. The averages below are "
            f"computed on stubs and should not be read as a robustness result.")

    is_avg = _avg([w["is_metric"] for w in scored])
    oos_avg = _avg([w["oos_metric"] for w in scored])
    degradation = (oos_avg - is_avg)
    # Ratio is only meaningful when the in-sample metric is positive.
    if is_avg <= 0:
        verdict = "inconclusive"        # in-sample optimization found no positive edge
    elif oos_avg <= 0:
        verdict = "likely-curve-fit"    # worked in-sample, broke out-of-sample
    elif oos_avg / is_avg >= 0.5:
        verdict = "robust"
    else:
        verdict = "likely-curve-fit"
    return {
        "metric": metric, "is_years": is_years, "oos_years": oos_years,
        "n_windows": len(windows), "windows": windows,
        # n_windows is every fold walked; n_windows_scored is how many the verdict actually rests
        # on. When they differ, the difference is truncated trailing folds — see `warnings`.
        "n_windows_scored": len(scored),
        "min_oos_days": _MIN_OOS_DAYS,
        "warnings": warnings,
        "is_avg": round(is_avg, 4), "oos_avg": round(oos_avg, 4),
        "degradation": round(degradation, 4),
        "oos_to_is_ratio": round((oos_avg / is_avg), 3) if is_avg else None,
        "verdict": verdict,
    }


def _avg(xs: list[float]) -> float:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0
