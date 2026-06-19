"""Declarative strategy layer: config schema (stable contract) + resolver to signals."""
from .schema import (  # noqa: F401
    Costs, RegimeFilter, StopLoss, StrategyConfig, TakeProfit, Universe, config_hash,
)
from .resolve import ResolvedStrategy, resolve  # noqa: F401
