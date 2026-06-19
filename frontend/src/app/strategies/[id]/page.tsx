"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";

const TEMPLATE = {
  name: "my_strategy",
  universe: { index: "nifty500", point_in_time: false, filters: ["adtv_cr >= 10"] },
  entry_filters: ["close > sma50", "close > sma200", "roc21 > 10", "rsi14 > 60"],
  rank_by: "roc21",
  rank_order: "desc",
  n_holdings: 10,
  weighting: "equal",
  rebalance: "weekly",
  entry_fill: "next_open",
  sector_cap: 2,
  stop_loss: { type: "atr", mult: 2.0, atr_period: 14 },
  take_profit: { type: "r_multiple", r: 2.0 },
  max_hold_days: 60,
  costs_bps: { brokerage: 3, stt: 10, slippage: 15 },
  capital: 1000000,
  start: "2018-01-01",
  end: "2026-06-12",
  benchmark: "NIFTY500",
};

export default function StrategyEditor() {
  const params = useParams();
  const router = useRouter();
  const id = String(params.id);
  const isNew = id === "new";

  const [name, setName] = useState(isNew ? "my_strategy" : "");
  const [text, setText] = useState(JSON.stringify(TEMPLATE, null, 2));
  const [sid, setSid] = useState<string | null>(isNew ? null : id);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (!isNew) {
      api.getStrategy(id)
        .then((s) => { setName(s.name); setText(JSON.stringify(s.config, null, 2)); setSid(s.id); })
        .catch((e) => setMsg(`load error: ${e.message}`));
    }
  }, [id, isNew]);

  function parse(): any | null {
    try { return JSON.parse(text); }
    catch (e) { setMsg(`Invalid JSON: ${(e as Error).message}`); return null; }
  }

  async function save(): Promise<string | null> {
    const cfg = parse(); if (!cfg) return null;
    setBusy("save");
    try {
      const s = await api.saveStrategy(name, cfg, sid ?? undefined);
      setSid(s.id); setMsg("Saved ✓");
      if (isNew) router.replace(`/strategies/${s.id}`);
      return s.id;
    } catch (e) { setMsg(`save failed: ${(e as Error).message}`); return null; }
    finally { setBusy(null); }
  }

  async function runBacktest() {
    const cfg = parse(); if (!cfg) return;
    const savedId = sid ?? (await save());
    setBusy("backtest");
    try {
      const res = await api.runBacktest(cfg, savedId, true);
      if (res.backtest_id) router.push(`/backtests/${res.backtest_id}`);
      else setMsg("backtest ran but was not saved");
    } catch (e) { setMsg(`backtest failed: ${(e as Error).message}`); }
    finally { setBusy(null); }
  }

  async function genSignals() {
    const cfg = parse(); if (!cfg) return;
    const savedId = sid ?? (await save());
    setBusy("signals");
    try {
      const r = await api.runSignals(cfg, savedId, true);
      setMsg(`Generated ${r.signals.length} signals as of ${r.as_of} — see Live Signals`);
    } catch (e) { setMsg(`signals failed: ${(e as Error).message}`); }
    finally { setBusy(null); }
  }

  return (
    <div className="max-w-4xl space-y-4">
      <h1 className="text-2xl font-semibold">{isNew ? "New strategy" : `Edit · ${name}`}</h1>
      <p className="text-muted text-sm">
        Declarative config. Filters reference indicators like <span className="mono">close</span>,{" "}
        <span className="mono">sma50</span>, <span className="mono">roc21</span>,{" "}
        <span className="mono">rsi14</span>, <span className="mono">adtv_cr</span>,{" "}
        <span className="mono">rel_strength63</span>. Each filter is ANDed.
      </p>

      <div className="flex items-center gap-3">
        <label className="text-sm text-muted">Name</label>
        <input className="bg-card border border-border rounded px-3 py-1.5 text-sm mono flex-1"
          value={name} onChange={(e) => setName(e.target.value)} />
      </div>

      <textarea
        className="w-full h-[460px] bg-card border border-border rounded-lg p-4 text-sm mono leading-relaxed"
        value={text} onChange={(e) => setText(e.target.value)} spellCheck={false}
      />

      {msg && <div className="card px-4 py-2 text-sm">{msg}</div>}

      <div className="flex gap-2">
        <button className="btn" onClick={save} disabled={!!busy}>{busy === "save" ? "saving…" : "Save"}</button>
        <button className="btn btn-accent" onClick={runBacktest} disabled={!!busy}>
          {busy === "backtest" ? "running…" : "Run backtest →"}
        </button>
        <button className="btn" onClick={genSignals} disabled={!!busy}>
          {busy === "signals" ? "…" : "Generate signals"}
        </button>
      </div>
    </div>
  );
}
