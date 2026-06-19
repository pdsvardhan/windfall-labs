"""Parameter sweep: run a strategy across a grid of overrides in one batch, ranked by a metric."""
from __future__ import annotations

import copy
import itertools

from ..engine.backtest import run_backtest
from ..strategy.schema import StrategyConfig


def apply_overrides(base: dict, overrides: dict) -> dict:
    """Apply dotted-path overrides (e.g. {'stop_loss.mult': 2.0, 'n_holdings': 15}) onto a copy."""
    cfg = copy.deepcopy(base)
    for path, value in overrides.items():
        node = cfg
        parts = path.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = value
    return cfg


def _grid_combos(grid: dict[str, list]) -> list[dict]:
    if not grid:
        return [{}]
    keys = list(grid.keys())
    return [dict(zip(keys, combo)) for combo in itertools.product(*[grid[k] for k in keys])]


def sweep(base_config: dict, grid: dict[str, list], metric: str = "sharpe",
          maximize: bool = True) -> dict:
    """Run every grid combination; return ranked variants by `metric`."""
    base = StrategyConfig(**base_config).model_dump()
    rows = []
    for combo in _grid_combos(grid):
        cfg = apply_overrides(base, combo)
        try:
            res = run_backtest(cfg)
            summ = res.summary.model_dump()
            rows.append({"overrides": combo, "metric": metric,
                         "value": summ.get(metric, 0.0), "summary": summ})
        except Exception as exc:  # noqa: BLE001
            rows.append({"overrides": combo, "error": repr(exc), "value": float("-inf")})
    rows.sort(key=lambda r: (r.get("value") if r.get("value") is not None else float("-inf")),
              reverse=maximize)
    return {"metric": metric, "maximize": maximize, "n_variants": len(rows), "ranked": rows}
