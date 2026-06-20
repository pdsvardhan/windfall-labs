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
];

// Fundamentals backed by the screener history (covers delisted names) — survivorship-safe.
export const OWN_FACTORS: FactorDef[] = [
  { token: "durability_own", label: "Durability (own, history-backed)", group: "Fundamental · survivorship-free" },
  { token: "valuation_own", label: "Valuation (own, history-backed)", group: "Fundamental · survivorship-free" },
  { token: "momentum_own", label: "Momentum (own, price-based)", group: "Fundamental · survivorship-free" },
  { token: "roe", label: "Return on equity %", group: "Fundamental · survivorship-free" },
  { token: "roa", label: "Return on assets %", group: "Fundamental · survivorship-free" },
  { token: "opm", label: "Operating margin %", group: "Fundamental · survivorship-free" },
  { token: "np_qtr_yoy", label: "Net-profit YoY %", group: "Fundamental · survivorship-free" },
];

// Trendlyne's own DVM + valuation + snapshot fundamentals — NOT available for delisted names.
export const TL_FACTORS: FactorDef[] = [
  { token: "tl_durability", label: "Trendlyne Durability (0-100)", group: "Trendlyne DVM · survivors-only", survivorsOnly: true },
  { token: "tl_valuation", label: "Trendlyne Valuation (0-100)", group: "Trendlyne DVM · survivors-only", survivorsOnly: true },
  { token: "tl_momentum", label: "Trendlyne Momentum (0-100)", group: "Trendlyne DVM · survivors-only", survivorsOnly: true },
  { token: "tl_pe", label: "P/E (TTM)", group: "Trendlyne DVM · survivors-only", survivorsOnly: true },
  { token: "tl_peg", label: "PEG (TTM)", group: "Trendlyne DVM · survivors-only", survivorsOnly: true },
  { token: "tl_pbv", label: "P/B", group: "Trendlyne DVM · survivors-only", survivorsOnly: true },
  { token: "tl_roe", label: "ROE (annual, result-lagged)", group: "Trendlyne DVM · survivors-only", survivorsOnly: true },
  { token: "tl_roce", label: "ROCE (annual, result-lagged)", group: "Trendlyne DVM · survivors-only", survivorsOnly: true },
  { token: "tl_de", label: "Debt/Equity (annual)", group: "Trendlyne DVM · survivors-only", survivorsOnly: true },
  { token: "piotroski", label: "Piotroski F (snapshot)", group: "Snapshot fundamentals · survivors-only", survivorsOnly: true },
  { token: "promoter_pledge", label: "Promoter pledge % (snapshot)", group: "Snapshot fundamentals · survivors-only", survivorsOnly: true },
  { token: "eps_growth", label: "EPS growth % (snapshot)", group: "Snapshot fundamentals · survivors-only", survivorsOnly: true },
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

export function defaultConfig(name = "new_strategy"): StrategyConfig {
  return {
    name,
    data_source: "trendlyne", // survivorship-free by default
    universe: { index: "trendlyne", point_in_time: true, filters: ["adtv_cr >= 5"], exclude_sectors: [] },
    entry_filters: ["close > sma200", "roc126 > 0"],
    rank_by: "roc126",
    rank_order: "desc",
    rank_blend: [],
    n_holdings: 15,
    weighting: "equal",
    invest_fully: true,
    max_weight_per_stock: null,
    rebalance: "monthly",
    entry_fill: "next_open",
    sector_cap: null,
    stop_loss: { type: "atr", mult: 2.5, atr_period: 14 },
    take_profit: { type: "none" },
    max_hold_days: null,
    max_position_adtv_pct: 0.1,
    regime_filter: { enabled: true, ma_period: 200, mode: "binary", below_exposure: 0.0 },
    costs_bps: { brokerage: 3, stt: 10, slippage: 15 },
    capital: 1000000,
    start: "2016-07-01",
    end: "2024-12-31",
    benchmark: "NIFTY500",
  };
}
