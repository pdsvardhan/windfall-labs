"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DataStatus } from "@/lib/types";
import { StatCard } from "@/components/StatCard";

const statusChip: Record<string, string> = {
  available: "border-gain/50 text-gain",
  snapshot: "border-accent/50 text-accent",
  partial: "border-warn/50 text-warn",
  deferred: "border-border text-muted",
  "not-loaded": "border-loss/50 text-loss",
};

export default function DataPage() {
  const [ds, setDs] = useState<DataStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function load() { api.dataStatus().then(setDs).catch((e) => setErr(e.message)); }
  useEffect(() => { load(); }, []);

  async function refresh() {
    setBusy(true);
    try { await api.refreshData(); load(); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <div className="max-w-5xl space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Data status</h1>
          <p className="text-muted text-sm">Coverage and the Phase-0 feasibility matrix. v1 uses current Nifty 500 membership (not yet survivorship-free).</p>
        </div>
        <button className="btn" onClick={refresh} disabled={busy}>{busy ? "refreshing…" : "Incremental refresh"}</button>
      </div>

      {err && <div className="card border-loss/50 px-4 py-2 text-loss text-sm">{err}</div>}
      {!ds ? <div className="text-muted">Loading…</div> : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard label="Price tickers" value={String(ds.coverage.n_tickers)} />
            <StatCard label="Universe size" value={String(ds.n_universe)} tone="muted" />
            <StatCard label="Fundamentals" value={ds.fundamentals ? String(ds.fundamentals.tickers) : "—"}
              tone="muted" sub={ds.fundamentals?.latest ? `snapshot ${ds.fundamentals.latest}` : "none"} />
            <StatCard label="Through" value={ds.coverage.date_max ?? "—"} tone="muted" />
          </div>

          <section>
            <h2 className="text-lg font-medium mb-2">Phase-0 feasibility matrix</h2>
            <div className="card scroll-y">
              <table className="data">
                <thead><tr><th>Data need</th><th>Source</th><th>Status</th><th>Detail</th></tr></thead>
                <tbody>
                  {ds.feasibility.map((f, i) => (
                    <tr key={i}>
                      <td className="text-fg whitespace-normal">{f.need}</td>
                      <td className="text-muted">{f.source}</td>
                      <td><span className={`chip ${statusChip[f.status] ?? "border-border text-muted"}`}>{f.status}</span></td>
                      <td className="text-muted whitespace-normal text-xs">{f.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
