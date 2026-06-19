"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { SignalRun, Strategy } from "@/lib/types";
import { SignalsTable } from "@/components/SignalsTable";

export default function SignalsPage() {
  const [strats, setStrats] = useState<Strategy[]>([]);
  const [sid, setSid] = useState<string>("");
  const [run, setRun] = useState<SignalRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.listStrategies().then((s) => { setStrats(s); if (s[0]) setSid(s[0].id); }).catch((e) => setErr(e.message));
  }, []);

  async function go() {
    const strat = strats.find((s) => s.id === sid);
    if (!strat) return;
    setBusy(true); setErr(null);
    try { setRun(await api.runSignals(strat.config, sid, true)); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }

  function downloadCsv() {
    if (!run) return;
    const cols = ["ticker", "action", "rank_value", "weight", "last_close", "entry_zone", "stop", "target", "rsi14"];
    const rows = run.signals.map((s) =>
      cols.map((c) => {
        const v = (s as unknown as Record<string, unknown>)[c];
        return v === null || v === undefined ? "" : String(v);
      }).join(","),
    );
    const csv = [cols.join(","), ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `signals_${run.as_of ?? "latest"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="max-w-5xl space-y-4">
      <h1 className="text-2xl font-semibold">Live signals</h1>
      <p className="text-muted text-sm">Today&apos;s buy / hold / sell list. You place every order — commit picks to the paper book to track them risk-free.</p>

      <div className="flex items-center gap-2">
        <select className="bg-card border border-border rounded px-3 py-1.5 text-sm" value={sid} onChange={(e) => setSid(e.target.value)}>
          {strats.length === 0 && <option>no strategies — create one first</option>}
          {strats.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <button className="btn btn-accent" onClick={go} disabled={busy || !sid}>{busy ? "running…" : "Run on latest data"}</button>
      </div>

      {err && <div className="card border-loss/50 px-4 py-2 text-loss text-sm">{err}</div>}

      {run && (
        <>
          <div className="flex items-center justify-between">
            <div className="text-sm text-muted mono">
              as of {run.as_of} · {run.signals.length} signals
              {typeof run.data_age_days === "number" && (
                <span className={run.data_age_days > 3 ? "text-warn ml-2" : "ml-2"}>
                  · data {run.data_age_days}d old
                </span>
              )}
              {run.regime?.enabled && (
                <span className={`ml-2 ${run.regime.index_above_ma ? "text-gain" : "text-loss"}`}>
                  · regime {run.regime.index_above_ma ? "RISK-ON" : `RISK-OFF (${(run.regime.exposure * 100).toFixed(0)}% exposure)`}
                </span>
              )}
            </div>
            <button className="btn text-xs" onClick={downloadCsv}>⬇ Export CSV</button>
          </div>
          {run.warnings?.length > 0 && (
            <div className="card border-warn/40 px-4 py-2 text-xs text-warn">{run.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}</div>
          )}
          <SignalsTable signals={run.signals} strategyId={sid} />
        </>
      )}
    </div>
  );
}
