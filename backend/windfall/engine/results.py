"""Standardized results schema — the contract the UI/assistant reads (Build-Spec section 7)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Summary(BaseModel):
    cagr: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    max_dd_dates: list[str] = Field(default_factory=list)
    sharpe: float = 0.0
    sortino: float = 0.0
    # CAGR / |max drawdown| — return per unit of worst peak-to-trough pain. Added 2026-09-07
    # (iter-172, to-do #250). It was NEVER computed: the iter-23 research harnesses
    # (docs/validation/*_iter23.py) all read `s.get("calmar")` off this summary and rendered
    # `(r.get('calmar') or 0)`, so every table they printed carried a calmar column of zeros and
    # the zero was read as a bug in the metric rather than its absence. 0.0 when max_drawdown is 0
    # (no drawdown yet / too short a series) — the ratio is undefined there, not infinite.
    calmar: float = 0.0
    volatility: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    annual_turnover: float = 0.0
    avg_holding_days: float = 0.0
    exposure: float = 0.0
    n_trades: int = 0
    benchmark_cagr: float = 0.0
    # None when the run took ~no exposure (0 trades / sat in cash): active return vs a
    # benchmark is not comparable then, and reporting a number invites the "+8.71% on
    # 0 trades" misread. `active_return_note` carries the reason when it is suppressed.
    active_return: float | None = None
    active_return_note: str = ""


class Trade(BaseModel):
    ticker: str
    entry_date: str
    entry: float
    exit_date: str | None = None
    exit: float | None = None
    return_pct: float = 0.0
    r_multiple: float | None = None
    exit_reason: str = "open"
    weight: float = 0.0
    holding_days: int = 0


class BacktestResult(BaseModel):
    config_hash: str
    name: str
    period: dict
    summary: Summary
    equity_curve: list[list] = Field(default_factory=list)     # [[date, nav], ...]
    drawdown_curve: list[list] = Field(default_factory=list)   # [[date, dd], ...]
    monthly_returns: list[list] = Field(default_factory=list)  # [[YYYY-MM, ret], ...]
    benchmark_curve: list[list] = Field(default_factory=list)  # [[date, nav], ...]
    trades: list[Trade] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
