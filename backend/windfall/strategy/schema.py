"""Strategy config schema — the stable contract the assistant/UI writes against.

Additive changes only; never silently rename a field. Mirrors Build-Spec section 5.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Universe(BaseModel):
    index: str = "nifty500"
    point_in_time: bool = False  # v1 uses current membership; honest flag, not yet survivorship-free
    filters: list[str] = Field(default_factory=list)  # e.g. ["adtv_cr >= 10", "durability > 50"]
    exclude_sectors: list[str] = Field(default_factory=list)  # e.g. ["Financial Services"]


class StopLoss(BaseModel):
    type: Literal["none", "pct", "atr", "trailing"] = "none"
    value: float | None = None  # for pct: fraction, e.g. 0.15
    mult: float | None = None   # for atr/trailing: ATR multiple, e.g. 2.0
    atr_period: int = 14

    @model_validator(mode="after")
    def _validate(self):
        if self.type == "pct" and self.value is not None and not 0 < self.value < 1:
            raise ValueError("stop-loss percent must be between 0 and 1 (e.g. 0.15 for 15%)")
        if self.type in ("atr", "trailing") and self.mult is not None and self.mult <= 0:
            raise ValueError("stop-loss ATR multiple must be greater than 0")
        return self


class TakeProfit(BaseModel):
    type: Literal["none", "pct", "r_multiple"] = "none"
    value: float | None = None  # for pct: fraction, e.g. 0.30
    r: float | None = None      # for r_multiple: e.g. 3.0

    @model_validator(mode="after")
    def _validate(self):
        if self.type == "pct" and self.value is not None and self.value <= 0:
            raise ValueError("take-profit percent must be greater than 0")
        if self.type == "r_multiple" and self.r is not None and self.r <= 0:
            raise ValueError("take-profit R-multiple must be greater than 0")
        return self


class Costs(BaseModel):
    brokerage: float = 3.0   # basis points per side
    stt: float = 10.0        # basis points per side
    slippage: float = 15.0   # basis points per side


class RankFactor(BaseModel):
    """One ingredient in a multi-factor percentile-blend ranking.

    `factor` is any rank expression (e.g. "roc125", "rs_nifty_3m", "roc125 / (atr14 / close)").
    At each rebalance the engine percentile-ranks the factor across that day's eligible names,
    then weight-blends all factors (higher blended score = better). `order` flips the sense so a
    "lower is better" factor (e.g. a valuation ratio) contributes its inverted percentile.
    Blank-tolerant: when a factor is NaN for a name (e.g. a fundamental before its snapshot) it is
    dropped for that name and the remaining factor weights renormalize.
    """
    factor: str
    weight: float = 1.0
    order: Literal["desc", "asc"] = "desc"  # desc = higher value is better (prefer high)


class RegimeFilter(BaseModel):
    """Index-trend overlay: scale down / go to cash when the index is below its moving average.

    The direct lever on drawdowns — a top-N momentum book run straight through 2018/2020/2022
    with no regime gate is what produces the -69% drawdowns.
    """
    enabled: bool = False
    benchmark: str | None = None             # defaults to the strategy benchmark when None
    ma_period: int = 200
    mode: Literal["binary", "scale"] = "binary"
    below_exposure: float = 0.0              # target exposure while index < its MA (0 = full cash)


class StrategyConfig(BaseModel):
    name: str = "unnamed_strategy"
    # "windfall" = the legacy yfinance/windfall.duckdb store (current-membership, snapshot DVM).
    # "trendlyne" = the survivorship-free Trendlyne full-history layer (adjusted OHLCV incl. delisted
    # names, point-in-time Rs500cr membership, real result-lag fundamentals, Trendlyne's own DVM).
    data_source: Literal["windfall", "trendlyne"] = "windfall"
    universe: Universe = Field(default_factory=Universe)
    entry_filters: list[str] = Field(default_factory=list)
    rank_by: str = "roc21"                     # single-factor rank (used when rank_blend is empty)
    rank_blend: list[RankFactor] = Field(default_factory=list)  # multi-factor percentile blend; overrides rank_by
    rank_order: Literal["desc", "asc"] = "desc"
    n_holdings: int = 10
    weighting: Literal["equal", "inverse_vol"] = "equal"
    invest_fully: bool = False                 # True: weight = 1/(qualifying names), no idle-cash drag
    max_weight_per_stock: float | None = None  # cap any single name's book weight (e.g. 0.20); excess redistributes
    rebalance: Literal["daily", "weekly", "fortnightly", "monthly", "quarterly"] = "weekly"
    entry_fill: Literal["next_open", "close"] = "next_open"
    stop_loss: StopLoss = Field(default_factory=StopLoss)
    take_profit: TakeProfit = Field(default_factory=TakeProfit)
    max_hold_days: int | None = None
    sector_cap: int | None = None              # max holdings per sector (methodology v2.2 used 2)
    max_position_adtv_pct: float = 0.10        # cap a position's notional vs its ADTV
    regime_filter: RegimeFilter = Field(default_factory=RegimeFilter)
    costs_bps: Costs = Field(default_factory=Costs)
    capital: float = 1_000_000.0
    start: str = "2015-01-01"
    end: str | None = None
    benchmark: str = "NIFTY500"

    @model_validator(mode="after")
    def _validate(self):
        # Server-side guardrails (iter-31): reject configs that would silently produce garbage
        # backtests/signals. Enforced here so EVERY endpoint that builds a StrategyConfig is covered.
        if self.capital < 1000:
            raise ValueError("capital must be at least ₹1,000")
        if self.end and self.start and self.end <= self.start:  # ISO dates compare lexically
            raise ValueError("end date must be after start date")
        if self.n_holdings < 1:
            raise ValueError("n_holdings must be at least 1")
        if self.max_hold_days is not None and self.max_hold_days < 1:
            raise ValueError("max_hold_days must be at least 1")
        if self.max_weight_per_stock is not None and not 0 < self.max_weight_per_stock <= 1:
            raise ValueError("max_weight_per_stock must be between 0 and 1 (a fraction, e.g. 0.2)")
        if self.sector_cap is not None and self.sector_cap < 1:
            raise ValueError("sector_cap must be at least 1")
        return self

    def hash(self) -> str:
        return config_hash(self)


def config_hash(cfg: StrategyConfig) -> str:
    payload = json.dumps(cfg.model_dump(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
