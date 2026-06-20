// Mirrors the backend pydantic models (windfall.engine.results, store_meta, signals_live).

export interface Summary {
  cagr: number;
  total_return: number;
  max_drawdown: number;
  max_dd_dates: string[];
  sharpe: number;
  sortino: number;
  volatility: number;
  win_rate: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
  annual_turnover: number;
  avg_holding_days: number;
  exposure: number;
  n_trades: number;
  benchmark_cagr: number;
  // null when the run had ~no exposure (0 trades / held cash): active return isn't
  // comparable then. active_return_note carries the reason when it's suppressed.
  active_return: number | null;
  active_return_note?: string;
}

export interface Trade {
  ticker: string;
  entry_date: string;
  entry: number;
  exit_date: string | null;
  exit: number | null;
  return_pct: number;
  r_multiple: number | null;
  exit_reason: string;
  weight: number;
  holding_days: number;
}

export interface BacktestResult {
  config_hash: string;
  name: string;
  period: { start: string; end: string; years: number; n_days: number };
  summary: Summary;
  equity_curve: [string, number][];
  drawdown_curve: [string, number][];
  monthly_returns: [string, number][];
  benchmark_curve: [string, number][];
  trades: Trade[];
  warnings: string[];
  backtest_id?: string;
}

export interface Strategy {
  id: string;
  name: string;
  config: Record<string, unknown>;
  updated_at?: string;
}

export interface BacktestRow {
  id: string;
  strategy_id: string | null;
  name: string;
  config_hash: string;
  created_at: string;
  summary: Summary;
}

export interface Signal {
  ticker: string;
  action: "buy" | "hold" | "sell";
  rank_value?: number;
  weight: number;
  last_close: number | null;
  entry_zone?: string;
  stop?: number | null;
  target?: number | null;
  ext_above_50dma?: number;
  rsi14?: number | null;
  note?: string;
}

export interface SignalRun {
  as_of: string | null;
  data_age_days?: number;
  strategy?: string;
  n_holdings?: number;
  regime?: { enabled: boolean; index_above_ma: boolean; ma_period: number; exposure: number } | null;
  signals: Signal[];
  warnings: string[];
  signal_run_id?: string;
}

export interface PaperPosition {
  id: string;
  strategy_id: string | null;
  ticker: string;
  status: string;
  entry_date: string;
  entry: number;
  stop: number | null;
  target: number | null;
  shares: number;
  last_price: number | null;
  last_date: string | null;
  exit: number | null;
  exit_date: string | null;
  return_pct: number | null;
  r_multiple: number | null;
  reason: string | null;
}

export interface ScoreRow {
  strategy_id: string;
  open: number;
  closed: number;
  total_pnl: number;
  win_rate: number;
  avg_return_pct: number;
  avg_r_multiple: number | null;
}

export interface Coverage {
  n_tickers: number;
  date_min: string | null;
  date_max: string | null;
  n_rows: number;
  last_fetch: Record<string, unknown> | null;
}

export interface FeasibilityRow {
  need: string;
  source: string;
  status: string;
  detail: string;
}

export interface FundamentalsCoverage {
  tickers: number;
  snapshots: number;
  latest: string | null;
  latest_age_days: number | null;
  stale: boolean;
  stale_after_days: number;
}

export interface FundamentalsStatus {
  coverage: FundamentalsCoverage;
  snapshots: string[];
  fields: string[];
}

export interface DataStatus {
  coverage: Coverage;
  n_universe: number;
  fundamentals?: FundamentalsCoverage;
  feasibility: FeasibilityRow[];
}

export interface WalkForwardReport {
  metric: string;
  n_windows: number;
  windows: {
    is_window: [string, string];
    oos_window: [string, string];
    best_overrides: Record<string, unknown>;
    is_metric: number;
    oos_metric: number;
  }[];
  is_avg: number;
  oos_avg: number;
  degradation: number;
  oos_to_is_ratio: number | null;
  verdict: string;
}

// ── strategy config (the recipe the builder edits) ──────────────────────────
export interface StrategyConfig {
  name: string;
  data_source: "windfall" | "trendlyne";
  universe: { index: string; point_in_time?: boolean; filters: string[]; exclude_sectors?: string[] };
  entry_filters: string[];
  rank_by: string;
  rank_order: "desc" | "asc";
  rank_blend?: { factor: string; weight: number; order: "desc" | "asc" }[];
  n_holdings: number;
  weighting: "equal" | "inverse_vol";
  invest_fully: boolean;
  max_weight_per_stock?: number | null;
  rebalance: "daily" | "weekly" | "fortnightly" | "monthly" | "quarterly";
  entry_fill: "next_open" | "close";
  sector_cap?: number | null;
  stop_loss: { type: "none" | "pct" | "atr" | "trailing"; value?: number | null; mult?: number | null; atr_period?: number };
  take_profit: { type: "none" | "pct" | "r_multiple"; value?: number | null; r?: number | null };
  max_hold_days?: number | null;
  max_position_adtv_pct?: number;
  regime_filter: { enabled: boolean; benchmark?: string | null; ma_period: number; mode: "binary" | "scale"; below_exposure: number };
  costs_bps: { brokerage: number; stt: number; slippage: number };
  capital: number;
  start: string;
  end: string | null;
  benchmark: string;
}

export interface Readiness {
  verdict: string;
  backtestable_from: string | null;
  summary: string;
  unknown_features?: string[];
  features?: { name: string; kind: string; coverage_from: string | null; source: string | null }[];
}

export interface BacktestResultFull extends BacktestResult {
  readiness?: Readiness;
}

export interface CostSensitivity {
  name: string;
  base_costs_bps: { brokerage: number; stt: number; slippage: number };
  multipliers: number[];
  runs: { cost_multiplier: number; summary: Partial<Summary> }[];
}

export interface SweepRow {
  overrides: Record<string, unknown>;
  value: number;
  summary?: Summary;
  error?: string;
}
export interface SweepResult {
  metric: string;
  maximize: boolean;
  n_variants: number;
  ranked: SweepRow[];
}
