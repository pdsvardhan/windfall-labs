"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { PaperPosition, ScoreRow } from "@/lib/types";
import { num, pct, signClass } from "@/lib/format";
import { StatCard } from "@/components/StatCard";

export default function PaperPage() {
  const [board, setBoard] = useState<ScoreRow[]>([]);
  const [positions, setPositions] = useState<PaperPosition[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    try { const [b, p] = await Promise.all([api.scoreboard(), api.paperPositions()]); setBoard(b); setPositions(p); }
    catch (e) { setErr((e as Error).message); }
  }
  useEffect(() => { load(); }, []);

  async function mark() {
    setBusy(true);
    try { await api.markPaper(); await load(); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }

  const totalPnl = board.reduce((a, r) => a + r.total_pnl, 0);
  const open = positions.filter((p) => p.status === "open").length;
  const closed = positions.filter((p) => p.status === "closed").length;

  return (
    <div className="max-w-6xl space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Paper trades</h1>
          <p className="text-muted text-sm">Simulated positions, marked-to-market. Prove the edge before real capital.</p>
        </div>
        <button className="btn" onClick={mark} disabled={busy}>{busy ? "marking…" : "Mark to market"}</button>
      </div>

      {err && <div className="card border-loss/50 px-4 py-2 text-loss text-sm">{err}</div>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Total P&L" value={`₹${totalPnl.toFixed(0)}`} tone={totalPnl >= 0 ? "gain" : "loss"} />
        <StatCard label="Open" value={String(open)} tone="muted" />
        <StatCard label="Closed" value={String(closed)} tone="muted" />
        <StatCard label="Strategies tracked" value={String(board.length)} tone="muted" />
      </div>

      {board.length > 0 && (
        <section>
          <h2 className="text-lg font-medium mb-2">Scoreboard</h2>
          <div className="card scroll-y">
            <table className="data">
              <thead><tr><th>Strategy</th><th>Open</th><th>Closed</th><th>Win rate</th><th>Avg return</th><th>Avg R</th><th>P&L</th></tr></thead>
              <tbody>
                {board.map((r) => (
                  <tr key={r.strategy_id}>
                    <td className="text-fg">{r.strategy_id}</td>
                    <td className="text-muted">{r.open}</td>
                    <td className="text-muted">{r.closed}</td>
                    <td>{pct(r.win_rate)}</td>
                    <td className={signClass(r.avg_return_pct)}>{pct(r.avg_return_pct)}</td>
                    <td>{r.avg_r_multiple !== null ? num(r.avg_r_multiple) : "—"}</td>
                    <td className={signClass(r.total_pnl)}>₹{r.total_pnl.toFixed(0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section>
        <h2 className="text-lg font-medium mb-2">Positions</h2>
        {positions.length === 0 ? (
          <div className="card px-4 py-6 text-muted text-sm">No paper positions. Commit a signal from Live Signals.</div>
        ) : (
          <div className="card scroll-y" style={{ maxHeight: 460 }}>
            <table className="data">
              <thead><tr><th>Ticker</th><th>Status</th><th>Entry</th><th>Stop</th><th>Target</th><th>Last</th><th>Return</th><th>Reason</th></tr></thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.id}>
                    <td className="text-fg">{p.ticker.replace(".NS", "")}</td>
                    <td className={p.status === "open" ? "text-accent" : "text-muted"}>{p.status}</td>
                    <td>{num(p.entry)}</td>
                    <td className="text-loss">{p.stop ? num(p.stop) : "—"}</td>
                    <td className="text-gain">{p.target ? num(p.target) : "—"}</td>
                    <td>{p.last_price ? num(p.last_price) : "—"}</td>
                    <td className={signClass(p.return_pct)}>{pct(p.return_pct)}</td>
                    <td className="text-muted">{p.reason ?? "—"}</td>
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
