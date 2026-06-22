import type {
  BacktestResult, BacktestResultFull, BacktestRow, CostSensitivity, Coverage, DataStatus,
  FundamentalsStatus, PaperPosition, Readiness, ScoreRow, SignalRun, Strategy, SweepResult,
  WalkForwardReport,
} from "./types";

// Same-origin by default: calls go to /api/* on whatever host serves the cockpit, and Next.js
// rewrites them to the API container (see next.config.mjs). Set NEXT_PUBLIC_API_BASE only for
// pointing a local dev frontend at a remote API.
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${text.slice(0, 300)}`);
  }
  return res.json() as Promise<T>;
}

const get = <T>(p: string) => http<T>(p);
const post = <T>(p: string, body: unknown) =>
  http<T>(p, { method: "POST", body: JSON.stringify(body) });
const del = <T>(p: string) => http<T>(p, { method: "DELETE" });

export const api = {
  health: () => get<{ status: string }>("/health"),
  coverage: () => get<Coverage>("/api/coverage"),
  dataStatus: () => get<DataStatus>("/api/data/status"),
  fundamentalsStatus: () => get<FundamentalsStatus>("/api/fundamentals/status"),
  refreshData: () => post<unknown>("/api/data/refresh", {}),

  listStrategies: () => get<Strategy[]>("/api/strategies"),
  getStrategy: (id: string) => get<Strategy>(`/api/strategies/${id}`),
  saveStrategy: (name: string, config: unknown, id?: string) =>
    post<Strategy>("/api/strategies", { name, config, id }),
  deleteStrategy: (id: string) => del<unknown>(`/api/strategies/${id}`),
  readiness: (config: unknown) => post<Readiness>("/api/strategies/readiness", { config }),

  runBacktest: (config: unknown, strategy_id?: string | null, save = true) =>
    post<BacktestResultFull>("/api/backtests", { config, strategy_id, save }),
  listBacktests: (strategy_id?: string) =>
    get<BacktestRow[]>(`/api/backtests${strategy_id ? `?strategy_id=${strategy_id}` : ""}`),
  getBacktest: (id: string) => get<BacktestResult>(`/api/backtests/${id}`),
  costSensitivity: (config: unknown, multipliers = [0, 1, 2]) =>
    post<CostSensitivity>("/api/backtests/cost-sensitivity", { config, multipliers }),

  sweep: (config: unknown, grid: unknown, metric = "sharpe") =>
    post<SweepResult>("/api/sweep", { config, grid, metric }),
  walkForward: (config: unknown, grid: unknown, metric = "sharpe", is_years = 3, oos_years = 1) =>
    post<WalkForwardReport>("/api/walkforward", { config, grid, metric, is_years, oos_years }),

  runSignals: (config: unknown, strategy_id?: string | null, save = false) =>
    post<SignalRun>("/api/signals", { config, strategy_id, save }),
  // signals CSV export is a non-JSON download; the page builds the URL via POST + blob.
  exportSignalsUrl: () => `${API_BASE}/api/signals/export`,
  surveillance: () => get<unknown[]>("/api/surveillance"),

  paperPositions: (strategy_id?: string, status?: string) =>
    get<PaperPosition[]>(
      `/api/paper/positions${
        strategy_id || status
          ? `?${[strategy_id && `strategy_id=${strategy_id}`, status && `status=${status}`]
              .filter(Boolean)
              .join("&")}`
          : ""
      }`,
    ),
  commitPaper: (strategy_id: string | null, signal: unknown) =>
    post<{ position_id: string }>("/api/paper/commit", { strategy_id, signal }),
  markPaper: () => post<unknown>("/api/paper/mark", {}),
  scoreboard: () => get<ScoreRow[]>("/api/paper/scoreboard"),

  validate: () => get<{ overall: string; checks: unknown[] }>("/api/validate"),
};
