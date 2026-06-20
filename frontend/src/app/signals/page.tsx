"use client";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import type { SignalRun, Strategy } from "@/lib/types";
import { num } from "@/lib/format";
import { Card, Pill } from "@/components/ui";

function SignalsInner() {
  const preselect = useSearchParams().get("strategy");
  const [strats, setStrats] = useState<Strategy[]>([]);
  const [sid, setSid] = useState<string>("");
  const [run, setRun] = useState<SignalRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.listStrategies().then((s) => {
      setStrats(s);
      setSid(preselect && s.some((x) => x.id === preselect) ? preselect : s[0]?.id || "");
    }).catch((e) => setErr(e.message));
  }, [preselect]);

  const strat = strats.find((s) => s.id === sid);

  async function generate() {
    if (!strat) return;
    setBusy(true); setErr(null); setRun(null);
    try { setRun(await api.runSignals(strat.config, strat.id, true)); }
    catch (e) { setErr(`signals failed: ${(e as Error).message}`); }
    finally { setBusy(false); }
  }

  async function exportCsv() {
    if (!strat) return;
    const res = await fetch(api.exportSignalsUrl(), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ config: strat.config }) });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = `signals_${run?.as_of || "today"}.csv`; a.click();
    URL.revokeObjectURL(url);
  }

  const cols = ".8fr 1.1fr 1.1fr .8fr .8fr .8fr .6fr .7fr 1fr";
  return (
    <div>
      <div className="flex items-end justify-between mt-6 mb-4 animate-rise">
        <div>
          <h1 className="text-[34px] font-extrabold tracking-tight">Live signals</h1>
          <p className="text-muted text-[14px] mt-1.5">Today's buy / hold / sell list for a strategy. You place every order. Surveillance (ASM/GSM) flags are shown — verify them before acting.</p>
        </div>
        {run && <button className="btn btn-soft" onClick={exportCsv}>⬇ Export CSV</button>}
      </div>

      <div className="flex flex-wrap items-center gap-2.5 mb-4">
        <select className="wf-in" style={{ width: "auto", minWidth: 240 }} value={sid} onChange={(e) => setSid(e.target.value)}>
          {strats.length === 0 && <option>no strategies — create one first</option>}
          {strats.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <button className="btn btn-ink" disabled={busy || !strat} onClick={generate}>{busy ? "running…" : "Run on latest data"}</button>
        {run && (
          <div className="ml-auto flex items-center gap-3.5 text-[12.5px] text-muted font-mono">
            <span>as of <b className="text-ink">{run.as_of}</b>{run.data_age_days != null ? ` · ${run.data_age_days}d old` : ""}</span>
            {run.regime && (
              <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-full font-sans font-bold" style={{ background: run.regime.index_above_ma ? "#e6f4ea" : "#fdeaf1", color: run.regime.index_above_ma ? "#1f7a4d" : "#c23e74" }}>
                <span className="w-2 h-2 rounded-full" style={{ background: run.regime.index_above_ma ? "#1f7a4d" : "#c23e74", animation: "wfPulse 1.8s infinite" }} />
                REGIME {run.regime.index_above_ma ? "RISK-ON" : "RISK-OFF"} · {Math.round((run.regime.exposure ?? 0) * 100)}%
              </span>
            )}
          </div>
        )}
      </div>

      {err && <Card className="px-4 py-3 mb-4" style={{ background: "#fdeaf1" }}><span className="text-loss text-[13px]">{err}</span></Card>}

      {!run ? (
        <Card className="px-5 py-10 text-center text-[13px] text-muted">Pick a strategy and run it to see today's orders.</Card>
      ) : run.signals.length === 0 ? (
        <Card className="px-5 py-8 text-center text-[13px] text-muted">No signals today {run.regime && !run.regime.index_above_ma ? "— regime is risk-off, the book is in cash." : "."}</Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="grid px-5 py-3 text-[11.5px] text-faint font-bold border-b" style={{ gridTemplateColumns: cols, borderColor: "#f0eef6" }}>
            <span>Action</span><span>Ticker</span><span>Entry zone</span><span className="text-right">Last ₹</span><span className="text-right">Stop</span><span className="text-right">Target</span><span className="text-right">RSI</span><span className="text-right">Wt</span><span className="text-right">Flag</span>
          </div>
          <div className="scroll-y" style={{ maxHeight: 560 }}>
            {run.signals.map((sig, i) => (
              <div key={i} className="wf-row grid px-5 py-2.5 text-[13px] items-center tn border-b" style={{ gridTemplateColumns: cols, borderColor: "#f6f4fb" }}>
                <span><Pill tone={sig.action === "buy" ? "buy" : sig.action === "sell" ? "sell" : "hold"}>{sig.action.toUpperCase()}</Pill></span>
                <span className="font-bold">{sig.ticker}</span>
                <span className="text-muted">{sig.entry_zone || "—"}</span>
                <span className="text-right">{sig.last_close != null ? sig.last_close.toLocaleString("en-IN") : "—"}</span>
                <span className="text-right text-loss">{sig.stop != null ? sig.stop.toLocaleString("en-IN") : "—"}</span>
                <span className="text-right text-gain">{sig.target != null ? sig.target.toLocaleString("en-IN") : "—"}</span>
                <span className="text-right text-faint">{sig.rsi14 != null ? num(sig.rsi14, 0) : "—"}</span>
                <span className="text-right text-faint">{sig.weight != null ? `${Math.round(sig.weight * 100)}%` : "—"}</span>
                <span className="text-right">{sig.note ? <span className="text-[10.5px] font-bold px-2 py-0.5 rounded-full" style={{ background: "#fff3da", color: "#9a6c12" }}>{sig.note}</span> : <span className="text-faint">—</span>}</span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

export default function SignalsPage() {
  return <Suspense fallback={<div className="mt-8 text-muted text-sm">Loading…</div>}><SignalsInner /></Suspense>;
}
