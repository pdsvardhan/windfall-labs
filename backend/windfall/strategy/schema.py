"""Strategy config schema — the stable contract the assistant/UI writes against.

Additive changes only; never silently rename a field. Mirrors Build-Spec section 5.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field


class Universe(BaseModel):
    index: str = "nifty500"
    point_in_time: bool = False  # v1 uses current membership; honest flag, not yet survivorship-free
    filters: list[str] = Field(default_factory=list)  # e.g. ["adtv_cr >= 10"]


class StopLoss(BaseModel):
    type: Literal["none", "pct", "atr", "trailing"] = "none"
    value: float | None = None  # for pct: fraction, e.g. 0.15
    mult: float | None = None   # for atr/trailing: ATR multiple, e.g. 2.0
    atr_period: int = 14


class TakeProfit(BaseModel):
    type: Literal["none", "pct", "r_multiple"] = "none"
    value: float | None = None  # for pct: fraction, e.g. 0.30
    r: float | None = None      # for r_multiple: e.g. 3.0


class Costs(BaseModel):
    brokerage: float = 3.0   # basis points per side
    stt: float = 10.0        # basis points per side
    slippage: float = 15.0   # basis points per side


class StrategyConfig(BaseModel):
    name: str = "unnamed_strategy"
    universe: Universe = Field(default_factory=Universe)
    entry_filters: list[str] = Field(default_factory=list)
    rank_by: str = "roc21"
    rank_order: Literal["desc", "asc"] = "desc"
    n_holdings: int = 10
    weighting: Literal["equal", "inverse_vol"] = "equal"
    rebalance: Literal["daily", "weekly", "fortnightly", "monthly"] = "weekly"
    entry_fill: Literal["next_open", "close"] = "next_open"
    stop_loss: StopLoss = Field(default_factory=StopLoss)
    take_profit: TakeProfit = Field(default_factory=TakeProfit)
    max_hold_days: int | None = None
    sector_cap: int | None = None              # max holdings per sector (methodology v2.2 used 2)
    max_position_adtv_pct: float = 0.10        # cap a position's notional vs its ADTV
    costs_bps: Costs = Field(default_factory=Costs)
    capital: float = 1_000_000.0
    start: str = "2015-01-01"
    end: str | None = None
    benchmark: str = "NIFTY500"

    def hash(self) -> str:
        return config_hash(self)


def config_hash(cfg: StrategyConfig) -> str:
    payload = json.dumps(cfg.model_dump(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
