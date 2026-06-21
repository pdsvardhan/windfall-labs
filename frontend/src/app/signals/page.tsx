"use client";

import { useEffect, useMemo, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import type { SignalRun, Strategy } from "@/lib/types";
import { num } from "@/lib/format";
import { Card, Pill } from "@/components/ui";

// mirrors the engine's NSE delivery cost model (windfall/engine/backtest.py)
const BUY_RATE = 0.0011862, SELL_RATE = 0.0010362, DP_FLAT = 15.93;

function nextRebalance(freq: string): Date {
  const d = new Date(); d.setHours(0, 0, 0, 0);
  if (freq === "daily") d.setDate(d.getDate() + 1);
  else if (freq === "weekly") d.setDate(d.getDate() + ((8 - d.getDay()) % 7 || 7)); // next Monday
  else if (freq === "fortnightly") d.setDate(d.getDate() + 14);
  else if (freq === "quarterly") d.setMonth(Math.floor(d.getMonth() / 3) * 3 + 3, 1);
  else d.setMonth(d.getMonth() + 1, 1); // monthly
  return d;
}

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
  const cfg = (strat?.config ?? {}) as any;
  const capital = cfg.capital ?? 100000;
  const nHoldings = cfg.n_holdings ?? 10;
  const rebalance = cfg.rebalance ?? "monthly";

  async function generate() {
    if (!strat) return;
    setBusy(true); setErr(null); setRun(null);
    try { setRun(await api.runSignals(strat.config, strat.id, true)); }
    catch (e) { setErr(`signals failed: ${(e as Error).message}`); }
    finally { setBusy(false); }
  }
  // Recompute on the latest data we hold whenever the selected strategy changes (owner pref iter-30).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (sid && strats.length) generate(); }, [sid]);

  async function exportCsv() {
    if (!strat) return;
    const res = await fetch(api.exportSignalsUrl(), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ config: strat.config }) });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = `signals_${run?.as_of || "today"}.csv`; a.click();
    URL.revokeObjectURL(url);
  }

  const qtyOf = (sig: any) => (sig.last_close && sig.weight ? Math.floor((capital * sig.weight) / sig.last_close) : null);

  // this-rebalance summary: buys/sells, estimated trading cost, next rebalance date
  const summary = useMemo(() => {
    if (!run?.signals?.length) return null;
    let buys = 0, sells = 0, buyTurn = 0;
    for (const s of run.signals as any[]) {
      if (s.action === "sell") { sells++; continue; }
      buys++; const q = qtyOf(s) ?? 0; buyTurn += q * (s.last_close ?? 0);
    }
    const sellTurn = sells * (capital / Math.max(nHoldings, 1));
    const estCost = buyTurn * BUY_RATE + sellTurn * SELL_RATE + sells * DP_FLAT;
    const nd = nextRebalance(rebalance);
    const days = Math.max(0, Math.ceil((nd.getTime() - Date.now()) / 86400000));
    return { buys, sells, estCost, nextStr: nd.toISOString().slice(0, 10), days };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run, capital, nHoldings, rebalance]);

  const cols = ".7fr 1fr .55fr .9fr .8fr .7fr .7fr .5fr .5fr .9fr";
  return (
    <div>
      <div className="flex items-end justify-between mt-6 mb-4 animate-rise">
        <div>
          <h1 className="text-[34px] font-extrabold tracking-tight">Live signals</h1>
          <p className="text-muted text-[14px] mt-1.5">Today's buy / hold / sell list for a strategy — entries at the next open, exactly as backtested. You place every order. Verify ASM/GSM flags before acting.</p>
        </div>
        {run && <button className="btn btn-soft" onClick={exportCsv}>⬇ Export CSV</button>}
      </div>

      <div className="flex flex-wrap items-center gap-2.5 mb-3">
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

      {summary && (
        <div className="flex flex-wrap gap-x-5 gap-y-1 mb-3 text-[12.5px] text-muted">
          <span>On ₹{(capital / 1e5).toFixed(2)}L: <b className="text-ink">{summary.buys}</b> buys{summary.sells ? <>, <b className="text-ink">{summary.sells}</b> sells</> : ""}</span>
          <span>Est. cost this rebalance <b className="text-ink">₹{Math.round(summary.estCost).toLocaleString("en-IN")}</b> <span className="text-faint">(incl. ₹15.93 DP/sell)</span></span>
          <span>Next rebalance <b className="text-ink">~{summary.nextStr}</b> <span className="text-faint">({summary.days}d)</span></span>
        </div>
      )}

      {!run ? (
        <Card className="px-5 py-10 text-center text-[13px] text-muted">Pick a strategy and run it to see today's orders.</Card>
      ) : run.signals.length === 0 ? (
        <Card className="px-5 py-8 text-center text-[13px] text-muted">No signals today {run.regime && !run.regime.index_above_ma ? "— regime is risk-off, the book is in cash." : "."}</Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="grid px-5 py-3 text-[11.5px] text-faint font-bold border-b" style={{ gridTemplateColumns: cols, borderColor: "#f0eef6" }}>
            <span>Action</span><span>Ticker</span><span className="text-right">Qty</span><span className="text-right">Amount ₹</span><span className="text-right">Last ₹</span><span className="text-right">Stop</span><span className="text-right">Target</span><span className="text-right">RSI</span><span className="text-right">Wt</span><span className="text-right">Flag</span>
          </div>
          <div className="scroll-y" style={{ maxHeight: 560 }}>
            {run.signals.map((sig, i) => {
              const q = qtyOf(sig);
              const amt = q != null && sig.last_close != null ? q * sig.last_close : null;
              return (
                <div key={i} className="wf-row grid px-5 py-2.5 text-[13px] items-center tn border-b" style={{ gridTemplateColumns: cols, borderColor: "#f6f4fb" }}>
                  <span><Pill tone={sig.action === "buy" ? "buy" : sig.action === "sell" ? "sell" : "hold"}>{sig.action.toUpperCase()}</Pill></span>
                  <span className="font-bold">{sig.ticker}</span>
                  <span className="text-right">{sig.action === "sell" ? "—" : q != null ? q.toLocaleString("en-IN") : "—"}</span>
                  <span className="text-right text-faint">{amt != null ? `₹${Math.round(amt).toLocaleString("en-IN")}` : "—"}</span>
                  <span className="text-right">{sig.last_close != null ? sig.last_close.toLocaleString("en-IN") : "—"}</span>
                  <span className="text-right text-loss">{sig.stop != null ? sig.stop.toLocaleString("en-IN") : "—"}</span>
                  <span className="text-right text-gain">{sig.target != null ? sig.target.toLocaleString("en-IN") : "—"}</span>
                  <span className="text-right text-faint">{sig.rsi14 != null ? num(sig.rsi14, 0) : "—"}</span>
                  <span className="text-right text-faint">{sig.weight != null ? `${Math.round(sig.weight * 100)}%` : "—"}</span>
                  <span className="text-right">{sig.note ? <span className="text-[10.5px] font-bold px-2 py-0.5 rounded-full" style={{ background: "#fff3da", color: "#9a6c12" }}>{sig.note}</span> : <span className="text-faint">—</span>}</span>
                </div>
              );
            })}
          </div>
        </Card>
      )}
    </div>
  );
}

export default function SignalsPage() {
  return <Suspense fallback={<div className="mt-8 text-muted text-sm">Loading…</div>}><SignalsInner /></Suspense>;
}
