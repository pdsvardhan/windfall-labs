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
  active_return: number;
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

export interface DataStatus {
  coverage: Coverage;
  n_universe: number;
  fundamentals?: { tickers: number; snapshots: number; latest: string | null };
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
