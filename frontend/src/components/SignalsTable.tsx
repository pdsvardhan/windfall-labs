"use client";

import { useState } from "react";
import type { Signal } from "@/lib/types";
import { api } from "@/lib/api";
import { num, pct } from "@/lib/format";

const actionChip: Record<string, string> = {
  buy: "border-gain/50 text-gain bg-gain/10",
  hold: "border-accent/50 text-accent bg-accent/10",
  sell: "border-loss/50 text-loss bg-loss/10",
};

export function SignalsTable({ signals, strategyId }: { signals: Signal[]; strategyId?: string | null }) {
  const [committed, setCommitted] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  async function commit(s: Signal) {
    setBusy(s.ticker);
    try {
      const res = await api.commitPaper(strategyId ?? null, s);
      setCommitted((c) => ({ ...c, [s.ticker]: res.position_id }));
    } catch (e) {
      alert(`commit failed: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  if (!signals.length) return <div className="text-muted text-sm">No signals.</div>;
  return (
    <div className="card scroll-y" style={{ maxHeight: 520 }}>
      <table className="data">
        <thead>
          <tr>
            <th>Action</th><th>Ticker</th><th>Zone</th><th>Last ₹</th><th>Stop</th>
            <th>Target</th><th>RSI</th><th>Wt</th><th></th>
          </tr>
        </thead>
        <tbody>
          {signals.map((s) => (
            <tr key={s.ticker}>
              <td><span className={`chip ${actionChip[s.action] ?? "border-border"}`}>{s.action}</span></td>
              <td className="text-fg">{s.ticker.replace(".NS", "")}</td>
              <td className="text-muted">{s.entry_zone ?? "—"}</td>
              <td>{s.last_close !== null ? num(s.last_close) : "—"}</td>
              <td className="text-loss">{s.stop ? num(s.stop) : "—"}</td>
              <td className="text-gain">{s.target ? num(s.target) : "—"}</td>
              <td className="text-muted">{s.rsi14 ?? "—"}</td>
              <td className="text-muted">{pct(s.weight, 1)}</td>
              <td>
                {s.action !== "sell" &&
                  (committed[s.ticker] ? (
                    <span className="text-xs text-gain">paper ✓</span>
                  ) : (
                    <button className="btn text-xs py-0.5" disabled={busy === s.ticker} onClick={() => commit(s)}>
                      {busy === s.ticker ? "…" : "→ paper"}
                    </button>
                  ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
