"""Windfall Labs quant engine.

The package is web/UI-agnostic: pure functions over data. The canonical contract is
``run_backtest(config) -> BacktestResult`` (see ``windfall.engine.backtest``). The CLI, the
FastAPI app and the cron scripts are thin wrappers over the same engine functions.
"""

__version__ = "0.1.0"
