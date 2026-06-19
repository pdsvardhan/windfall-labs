"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { BacktestRow, Coverage, Strategy } from "@/lib/types";
import { pct } from "@/lib/format";
import { StatCard } from "@/components/StatCard";

export default function Home() {
  const [cov, setCov] = useState<Coverage | null>(null);
  const [strats, setStrats] = useState<Strategy[]>([]);
  const [backtests, setBacktests] = useState<BacktestRow[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.coverage(), api.listStrategies(), api.listBacktests()])
      .then(([c, s, b]) => { setCov(c); setStrats(s); setBacktests(b); })
      .catch((e) => setErr(e.message));
  }, []);

  async function runValidation() {
    setValidating(true);
    try { const r = await api.validate(); setValidation(r.overall); }
    catch (e) { setValidation(`error: ${(e as Error).message}`); }
    finally { setValidating(false); }
  }

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Cockpit</h1>
          <p className="text-muted text-sm">Backtest, validate and act on systematic NSE strategies.</p>
        </div>
        <div className="flex gap-2">
          <button className="btn" onClick={runValidation} disabled={validating}>
            {validating ? "validating…" : "Validate engine"}
          </button>
          <Link className="btn btn-accent" href="/strategies/new">+ New strategy</Link>
        </div>
      </div>

      {err && <div className="card border-loss/50 px-4 py-3 text-loss text-sm">API error: {err} — is the backend API running on :8505?</div>}
      {validation && <div className="card px-4 py-2 text-sm">Validation: <span className="mono">{validation}</span></div>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Tickers loaded" value={cov ? String(cov.n_tickers) : "…"} />
        <StatCard label="Price rows" value={cov ? cov.n_rows.toLocaleString() : "…"} tone="muted" />
        <StatCard label="History from" value={cov?.date_min ?? "…"} tone="muted" />
        <StatCard label="Through" value={cov?.date_max ?? "…"} tone="muted" />
      </div>

      <section>
        <h2 className="text-lg font-medium mb-2">Strategies</h2>
        {strats.length === 0 ? (
          <div className="card px-4 py-6 text-muted text-sm">
            No strategies yet. <Link className="text-accent" href="/strategies/new">Create your first</Link> to run a backtest.
          </div>
        ) : (
          <div className="grid md:grid-cols-2 gap-3">
            {strats.map((s) => (
              <Link key={s.id} href={`/strategies/${s.id}`} className="card px-4 py-3 hover:bg-white/5">
                <div className="font-medium">{s.name}</div>
                <div className="text-xs text-muted mono mt-1">
                  {String((s.config as any)?.rebalance ?? "")} · top {String((s.config as any)?.n_holdings ?? "")} · {s.id}
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="text-lg font-medium mb-2">Recent backtests</h2>
        {backtests.length === 0 ? (
          <div className="text-muted text-sm">None yet.</div>
        ) : (
          <div className="card scroll-y" style={{ maxHeight: 320 }}>
            <table className="data">
              <thead><tr><th>Name</th><th>CAGR</th><th>Max DD</th><th>Sharpe</th><th>Turnover</th><th>When</th></tr></thead>
              <tbody>
                {backtests.map((b) => (
                  <tr key={b.id} className="cursor-pointer" onClick={() => (window.location.href = `/backtests/${b.id}`)}>
                    <td className="text-fg">{b.name}</td>
                    <td className={b.summary.cagr >= 0 ? "text-gain" : "text-loss"}>{pct(b.summary.cagr)}</td>
                    <td className="text-loss">{pct(b.summary.max_drawdown)}</td>
                    <td>{b.summary.sharpe.toFixed(2)}</td>
                    <td className="text-warn">{(b.summary.annual_turnover * 100).toFixed(0)}%</td>
                    <td className="text-muted">{b.created_at?.slice(0, 16)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
