"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Strategy, WalkForwardReport } from "@/lib/types";
import { num } from "@/lib/format";

const DEFAULT_GRID = {
  n_holdings: [8, 10, 15],
  "stop_loss.mult": [1.5, 2.0, 3.0],
  rebalance: ["weekly", "fortnightly"],
};

export default function WalkForwardPage() {
  const [strats, setStrats] = useState<Strategy[]>([]);
  const [sid, setSid] = useState("");
  const [grid, setGrid] = useState(JSON.stringify(DEFAULT_GRID, null, 2));
  const [metric, setMetric] = useState("sharpe");
  const [report, setReport] = useState<WalkForwardReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.listStrategies().then((s) => { setStrats(s); if (s[0]) setSid(s[0].id); }).catch((e) => setErr(e.message));
  }, []);

  async function go() {
    const strat = strats.find((s) => s.id === sid);
    if (!strat) return;
    let g: unknown;
    try { g = JSON.parse(grid); } catch (e) { setErr(`grid JSON: ${(e as Error).message}`); return; }
    setBusy(true); setErr(null); setReport(null);
    try { setReport(await api.walkForward(strat.config, g, metric, 3, 1)); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <div className="max-w-5xl space-y-4">
      <h1 className="text-2xl font-semibold">Walk-forward</h1>
      <p className="text-muted text-sm">Optimize in-sample, test out-of-sample, roll across history. The curve-fitting check — a strategy that only works in-sample is rejected.</p>

      <div className="flex flex-wrap items-center gap-2">
        <select className="bg-card border border-border rounded px-3 py-1.5 text-sm" value={sid} onChange={(e) => setSid(e.target.value)}>
          {strats.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <select className="bg-card border border-border rounded px-3 py-1.5 text-sm" value={metric} onChange={(e) => setMetric(e.target.value)}>
          {["sharpe", "cagr", "sortino", "total_return"].map((m) => <option key={m}>{m}</option>)}
        </select>
        <button className="btn btn-accent" onClick={go} disabled={busy || !sid}>{busy ? "rolling…" : "Run walk-forward"}</button>
      </div>

      <div>
        <label className="text-sm text-muted">Parameter grid</label>
        <textarea className="w-full h-40 bg-card border border-border rounded-lg p-3 text-sm mono mt-1"
          value={grid} onChange={(e) => setGrid(e.target.value)} spellCheck={false} />
      </div>

      {err && <div className="card border-loss/50 px-4 py-2 text-loss text-sm">{err}</div>}

      {report && (
        <div className="space-y-3">
          <div className={`card px-4 py-3 ${report.verdict === "robust" ? "border-gain/50" : "border-loss/50"}`}>
            <span className="text-sm">Verdict: </span>
            <span className={`font-semibold ${report.verdict === "robust" ? "text-gain" : "text-loss"}`}>{report.verdict}</span>
            <span className="text-muted text-sm mono ml-3">
              IS avg {num(report.is_avg)} → OOS avg {num(report.oos_avg)} (ratio {report.oos_to_is_ratio ?? "—"})
            </span>
          </div>
          <div className="card scroll-y">
            <table className="data">
              <thead><tr><th>IS window</th><th>OOS window</th><th>IS {metric}</th><th>OOS {metric}</th><th>Best params</th></tr></thead>
              <tbody>
                {report.windows.map((w, i) => (
                  <tr key={i}>
                    <td className="text-muted">{w.is_window[0]}→{w.is_window[1]}</td>
                    <td className="text-muted">{w.oos_window[0]}→{w.oos_window[1]}</td>
                    <td>{num(w.is_metric)}</td>
                    <td className={w.oos_metric >= w.is_metric * 0.5 ? "text-gain" : "text-loss"}>{num(w.oos_metric)}</td>
                    <td className="text-muted text-xs">{JSON.stringify(w.best_overrides)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
