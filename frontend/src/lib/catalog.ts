// The variable catalog the engine understands (mirrors backend resolve.py). Drives the guided
// builder's pickers, the Reference page, and — critically — the survivorship classification:
// a factor that has NO data for delisted names forces the run to "survivors-only".
import type { StrategyConfig } from "./types";

export interface FactorDef {
  token: string;        // base token or {N} template, e.g. "sma{N}", "roc{N}", "tl_durability"
  label: string;
  group: string;
  survivorsOnly?: boolean; // true = no data for delisted names
  param?: boolean;      // true = takes a period N
  note?: string;
}

// Price & technical — full history incl. delisted names (survivorship-safe).
export const PRICE_FACTORS: FactorDef[] = [
  { token: "close", label: "Close price", group: "Price" },
  { token: "open", label: "Open price", group: "Price" },
  { token: "high", label: "High", group: "Price" },
  { token: "low", label: "Low", group: "Price" },
  { token: "volume", label: "Volume", group: "Price" },
  { token: "adtv_cr", label: "Avg daily turnover (₹cr)", group: "Liquidity", note: "20-day ₹ traded value" },
  { token: "sma{N}", label: "Simple MA (N)", group: "Trend", param: true },
  { token: "ema{N}", label: "Exponential MA (N)", group: "Trend", param: true },
  { token: "roc{N}", label: "Rate of change % (N)", group: "Momentum", param: true },
  { token: "rsi{N}", label: "RSI (N)", group: "Momentum", param: true },
  { token: "atr{N}", label: "ATR (N)", group: "Volatility", param: true },
  { token: "adx{N}", label: "ADX trend strength (N)", group: "Trend", param: true },
  { token: "dist_high{N}", label: "Dist from N-day high %", group: "Momentum", param: true },
  { token: "rel_strength{N}", label: "Relative strength vs index (N)", group: "Momentum", param: true },
  { token: "adtv{N}", label: "Avg daily turnover ₹ (N)", group: "Liquidity", param: true },
  { token: "vol_avg{N}", label: "Avg volume (N)", group: "Liquidity", param: true },
  { token: "macd", label: "MACD", group: "Momentum" },
  { token: "macd_signal", label: "MACD signal", group: "Momentum" },
  { token: "macd_hist", label: "MACD histogram", group: "Momentum" },
  { token: "mcap", label: "Market cap (₹cr, point-in-time)", group: "Size · survivorship-free", note: "PIT mcap from universe membership — reproduces Trendlyne Market-Cap bands over history (mcap > 1000, mcap < 50000)" },
];

// Raw fundamentals backed by the screener history (covers delisted names) — survivorship-safe.
// (own-DVM composites removed iter-31; use these raw factors or Trendlyne's tl_DVM directly.)
export const OWN_FACTORS: FactorDef[] = [
  { token: "roe", label: "Return on equity %", group: "Fundamental · survivorship-free" },
  { token: "roa", label: "Return on assets %", group: "Fundamental · survivorship-free" },
  { token: "opm", label: "Operating margin %", group: "Fundamental · survivorship-free" },
  { token: "np_qtr_yoy", label: "Net-profit YoY %", group: "Fundamental · survivorship-free" },
  { token: "pe", label: "P/E (price ÷ EPS)", group: "Fundamental · survivorship-free" },
  { token: "pb", label: "P/B (price ÷ book)", group: "Fundamental · survivorship-free" },
];

// Trendlyne's own DVM + valuation + fundamentals — NOT available for delisted names (survivors-only).
// All result-lagged fundamentals are point-in-time (no look-ahead). iter-32 widened this from the
// DVM core to a curated library (data was already in trendlyne.duckdb, just not wired).
export const TL_FACTORS: FactorDef[] = [
  { token: "tl_durability", label: "Trendlyne Durability (0-100)", group: "Trendlyne DVM · survivors-only", survivorsOnly: true },
  { token: "tl_valuation", label: "Trendlyne Valuation (0-100)", group: "Trendlyne DVM · survivors-only", survivorsOnly: true },
  { token: "tl_momentum", label: "Trendlyne Momentum (0-100)", group: "Trendlyne DVM · survivors-only", survivorsOnly: true },
  { token: "tl_pe", label: "P/E TTM (Trendlyne, ≤0 dropped)", group: "Trendlyne valuation · survivors-only", survivorsOnly: true },
  { token: "tl_peg", label: "PEG TTM (Trendlyne, ≤0 dropped)", group: "Trendlyne valuation · survivors-only", survivorsOnly: true },
  { token: "tl_pbv", label: "P/B (Trendlyne)", group: "Trendlyne valuation · survivors-only", survivorsOnly: true },
  { token: "tl_eyield", label: "Earnings yield % (annual)", group: "Trendlyne valuation · survivors-only", survivorsOnly: true },
  { token: "tl_ps", label: "Price/Sales (annual)", group: "Trendlyne valuation · survivors-only", survivorsOnly: true },
  { token: "tl_roe", label: "ROE % (annual, result-lagged)", group: "Trendlyne fundamentals · survivors-only", survivorsOnly: true },
  { token: "tl_roce", label: "ROCE % (annual, result-lagged)", group: "Trendlyne fundamentals · survivors-only", survivorsOnly: true },
  { token: "tl_roic", label: "ROIC % (annual, result-lagged)", group: "Trendlyne fundamentals · survivors-only", survivorsOnly: true },
  { token: "tl_de", label: "Debt/Equity (annual)", group: "Trendlyne fundamentals · survivors-only", survivorsOnly: true },
  { token: "tl_opm", label: "Operating margin % (annual)", group: "Trendlyne fundamentals · survivors-only", survivorsOnly: true },
  { token: "tl_eps", label: "EPS (annual, result-lagged)", group: "Trendlyne fundamentals · survivors-only", survivorsOnly: true },
  { token: "tl_cfo", label: "Cash from ops ₹ (annual)", group: "Trendlyne fundamentals · survivors-only", survivorsOnly: true },
  { token: "tl_current_ratio", label: "Current ratio (annual)", group: "Trendlyne fundamentals · survivors-only", survivorsOnly: true },
  { token: "tl_quick_ratio", label: "Quick ratio (annual)", group: "Trendlyne fundamentals · survivors-only", survivorsOnly: true },
  { token: "tl_int_cover", label: "Interest coverage (annual)", group: "Trendlyne fundamentals · survivors-only", survivorsOnly: true },
  { token: "tl_piotroski", label: "Piotroski F (result-lagged)", group: "Trendlyne quality · survivors-only", survivorsOnly: true },
  { token: "tl_np_growth", label: "Net-profit TTM growth %", group: "Trendlyne quality · survivors-only", survivorsOnly: true },
  { token: "tl_rev_growth", label: "Revenue TTM growth %", group: "Trendlyne quality · survivors-only", survivorsOnly: true },
  { token: "tl_pledge", label: "Promoter pledge % (result-lagged)", group: "Trendlyne ownership · survivors-only", survivorsOnly: true, note: "shareholding history starts 2023 — NaN (fails filter) before then" },
  { token: "tl_fii", label: "FII holding % (result-lagged)", group: "Trendlyne ownership · survivors-only", survivorsOnly: true, note: "shareholding history starts 2023" },
  { token: "tl_dii", label: "DII holding % (result-lagged)", group: "Trendlyne ownership · survivors-only", survivorsOnly: true, note: "shareholding history starts 2023" },
  // Live-only snapshot factor (from the single Trendlyne snapshot): NaN before the snapshot date, so
  // it silently no-ops in a historical backtest — use only for live signals. (piotroski/pledge moved
  // to the result-lagged tl_* versions above; eps_growth has no historical series yet.)
  { token: "eps_growth", label: "EPS growth % (LIVE ONLY — no backtest)", group: "Snapshot · live signals only", survivorsOnly: true, note: "NaN before the snapshot date; does nothing in a historical backtest" },
];

export const ALL_FACTORS = [...PRICE_FACTORS, ...OWN_FACTORS, ...TL_FACTORS];

// Bare tokens that have NO delisted-name data; parametric ones never do here so we list bases.
const SURVIVORS_ONLY_TOKENS = new Set(TL_FACTORS.map((f) => f.token));

export const OPERATORS = [">=", "<=", ">", "<", "=="];

export const INDEXES = [
  { value: "trendlyne", label: "Trendlyne universe (survivorship-free, ~1,900)" },
  { value: "nifty500", label: "Nifty 500" },
  { value: "niftytotalmarket", label: "Nifty Total Market (~750)" },
];
export const BENCHMARKS = [
  { value: "NIFTY500", label: "NIFTY 500" },
  { value: "NIFTY50", label: "NIFTY 50" },
  { value: "NIFTYMIDCAP", label: "Nifty Midcap" },
];
export const FREQUENCIES = ["daily", "weekly", "fortnightly", "monthly", "quarterly"] as const;

// Tokenize every expression in a config and decide if any referenced factor lacks dead-name data.
const WORD = /[a-zA-Z_][a-zA-Z0-9_]*/g;
export function referencedTokens(cfg: Partial<StrategyConfig>): string[] {
  const exprs: string[] = [
    ...(cfg.universe?.filters || []),
    ...(cfg.entry_filters || []),
    cfg.rank_by || "",
    ...((cfg.rank_blend || []).map((r) => r.factor)),
  ];
  const out = new Set<string>();
  for (const e of exprs) for (const m of e.match(WORD) || []) out.add(m);
  return [...out];
}

export function survivorsOnly(cfg: Partial<StrategyConfig>): { survivorsOnly: boolean; offenders: string[] } {
  const offenders = referencedTokens(cfg).filter((t) => SURVIVORS_ONLY_TOKENS.has(t));
  return { survivorsOnly: offenders.length > 0, offenders };
}

// Blank slate (owner pref iter-30): nothing pre-screened, no entry rules, no sort, no default
// exits/regime — the user builds everything explicitly. Only structural, non-opinionated defaults
// remain (data source, holdings count, equal weighting, monthly rebalance, costs, window).
export function defaultConfig(name = ""): StrategyConfig {
  return {
    name,
    data_source: "trendlyne", // survivorship-free by default
    universe: { index: "trendlyne", point_in_time: true, filters: [], exclude_sectors: [] },
    entry_filters: [],
    rank_by: "",
    rank_order: "desc",
    rank_blend: [],
    n_holdings: 15,
    weighting: "equal",
    invest_fully: true,
    max_weight_per_stock: null,
    rebalance: "monthly",
    entry_fill: "next_open",
    sector_cap: null,
    stop_loss: { type: "none", mult: 2.5, atr_period: 14 },
    take_profit: { type: "none" },
    max_hold_days: null,
    max_position_adtv_pct: 0.1,
    regime_filter: { enabled: false, ma_period: 200, mode: "binary", below_exposure: 0.0 },
    costs_bps: { brokerage: 3, stt: 10, slippage: 15 },
    capital: 100000,
    start: "2016-07-01",
    end: "2024-12-31",
    benchmark: "NIFTY500",
  };
}
