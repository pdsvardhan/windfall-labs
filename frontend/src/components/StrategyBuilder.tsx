"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Readiness, StrategyConfig, SweepResult } from "@/lib/types";
import { ALL_FACTORS, OPERATORS, FREQUENCIES, BENCHMARKS, defaultConfig, survivorsOnly } from "@/lib/catalog";
import { num, pctSigned } from "@/lib/format";
import { Card, Field, Switch, Segmented, Slider, SectionTitle } from "@/components/ui";
import { JsonView } from "@/components/JsonView";

// curated ready-to-use tokens for the pickers (parametric instances pre-baked)
const QUICK = [
  "close", "open", "high", "low", "adtv_cr",
  "sma50", "sma100", "sma200", "ema50", "ema200",
  "roc21", "roc63", "roc126", "roc252", "rsi14", "atr14", "adx14",
  "dist_high252", "rel_strength126",
  "durability_own", "valuation_own", "momentum_own", "roe", "roa", "opm", "np_qtr_yoy",
  "tl_durability", "tl_valuation", "tl_momentum", "tl_pe", "tl_peg", "tl_pbv", "tl_roe", "tl_roce", "tl_de",
  "piotroski", "promoter_pledge", "eps_growth",
];
const FACTOR_BY_TOKEN = Object.fromEntries(ALL_FACTORS.map((f) => [f.token, f]));

function set(obj: any, path: string[], val: any) {
  const o = { ...obj }; let cur = o;
  for (let i = 0; i < path.length - 1; i++) { cur[path[i]] = { ...cur[path[i]] }; cur = cur[path[i]]; }
  cur[path[path.length - 1]] = val; return o;
}

export function StrategyBuilder({ initial }: { initial?: { id: string; name: string; config: StrategyConfig } }) {
  const router = useRouter();
  const [cfg, setCfg] = useState<StrategyConfig>(initial?.config || defaultConfig());
  const [name, setName] = useState(initial?.name || "new_strategy");
  const [sid, setSid] = useState<string | null>(initial?.id || null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const upd = (path: string[], v: any) => setCfg((c) => set(c, path, v));
  const sv = useMemo(() => survivorsOnly(cfg), [cfg]);
  const fullCfg = useMemo(() => ({ ...cfg, name }), [cfg, name]);

  // debounced readiness check
  const t = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => {
    clearTimeout(t.current);
    t.current = setTimeout(() => { api.readiness(fullCfg).then(setReadiness).catch(() => setReadiness(null)); }, 500);
    return () => clearTimeout(t.current);
  }, [fullCfg]);

  async function save(): Promise<string | null> {
    setBusy("save"); setMsg(null);
    try { const s = await api.saveStrategy(name, fullCfg, sid ?? undefined); setSid(s.id); setMsg("Saved ✓"); return s.id; }
    catch (e) { setMsg(`save failed: ${(e as Error).message}`); return null; }
    finally { setBusy(null); }
  }
  async function run() {
    setBusy("run"); setMsg(null);
    const id = sid ?? (await save());
    try {
      const res = await api.runBacktest(fullCfg, id, true);
      if (res.backtest_id && id) router.push(`/strategies/${id}`);
      else setMsg("ran, but could not save — check the config");
    } catch (e) { setMsg(`backtest failed: ${(e as Error).message}`); }
    finally { setBusy(null); }
  }

  return (
    <div>
      <div className="flex items-end justify-between mt-6 mb-4 animate-rise">
        <div>
          <div className="text-[13px] text-faint font-bold uppercase tracking-wide">Strategy builder</div>
          <input className="bg-transparent text-[34px] font-extrabold tracking-tight outline-none mt-1 w-full"
            value={name} onChange={(e) => setName(e.target.value)} />
          <p className="text-muted text-[14px] mt-1">Screen → rank → size → backtest. The JSON on the right mirrors every control. Survivorship-free by default.</p>
        </div>
      </div>

      <div className="grid lg:grid-cols-[1.65fr_1fr] gap-4 items-start">
        {/* ── FORM ── */}
        <div className="grid md:grid-cols-2 gap-3.5">
          {/* Universe / screener */}
          <Card className="p-5 md:col-span-2">
            <SectionTitle dot="#a9c9f2">Universe &amp; screener</SectionTitle>
            <div className="flex items-center justify-between p-3 rounded-xl mb-3" style={{ background: sv.survivorsOnly ? "#fff3da" : "#eef6dd" }}>
              <div>
                <div className="text-[13px] font-bold">{sv.survivorsOnly ? "Survivors-only universe" : "Survivorship-free universe"}</div>
                <div className="text-[11.5px] text-muted">
                  {sv.survivorsOnly
                    ? `Auto-off: ${sv.offenders.join(", ")} has no data for delisted names`
                    : "NSE names >₹500cr point-in-time, incl. delisted"}
                </div>
              </div>
              <Switch on={!sv.survivorsOnly} disabled />
            </div>
            <FilterBuilder label="Screener filters (qualify the universe)" placeholder="e.g. adtv_cr >= 5"
              list={cfg.universe.filters} onChange={(l) => upd(["universe", "filters"], l)} />
          </Card>

          {/* Entry & ranking */}
          <Card className="p-5 md:col-span-2">
            <SectionTitle dot="#b9d24a">Entry &amp; ranking</SectionTitle>
            <FilterBuilder label="Entry filters (all must pass)" placeholder="e.g. close > sma200"
              list={cfg.entry_filters} onChange={(l) => upd(["entry_filters"], l)} />
            <div className="grid grid-cols-[1.4fr_1fr] gap-3.5 mt-4">
              <Field label="Sort by (rank variable)">
                <FactorSelect value={cfg.rank_by} onChange={(v) => upd(["rank_by"], v)} />
              </Field>
              <div>
                <span className="text-[12px] font-bold text-muted">Order</span>
                <Segmented value={cfg.rank_order} onChange={(v) => upd(["rank_order"], v)}
                  options={[{ value: "desc", label: "Max first" }, { value: "asc", label: "Min first" }]} />
              </div>
            </div>
          </Card>

          {/* Sizing */}
          <Card className="p-5">
            <SectionTitle dot="#f5e049">Position sizing</SectionTitle>
            <div className="flex items-center justify-between"><span className="text-[12.5px] font-bold text-muted">Holdings</span><span className="text-[20px] font-extrabold">{cfg.n_holdings}</span></div>
            <Slider value={cfg.n_holdings} min={3} max={50} onChange={(v) => upd(["n_holdings"], v)} />
            <div className="mt-4"><span className="text-[12px] font-bold text-muted">Weighting</span>
              <Segmented value={cfg.weighting} onChange={(v) => upd(["weighting"], v)}
                options={[{ value: "equal", label: "Equal" }, { value: "inverse_vol", label: "Inverse-vol" }]} />
            </div>
            <div className="flex items-center justify-between mt-4 p-3 rounded-xl" style={{ background: "#f7f5fc" }}>
              <div><div className="text-[13px] font-bold">Invest fully</div><div className="text-[11.5px] text-faint">No idle-cash drag</div></div>
              <Switch on={cfg.invest_fully} onClick={() => upd(["invest_fully"], !cfg.invest_fully)} />
            </div>
            <div className="grid grid-cols-2 gap-3 mt-3.5">
              <Field label="Max weight / stock"><input className="wf-in mt-1.5" type="number" step="0.05" value={cfg.max_weight_per_stock ?? ""} placeholder="none" onChange={(e) => upd(["max_weight_per_stock"], e.target.value === "" ? null : parseFloat(e.target.value))} /></Field>
              <Field label="Sector cap"><input className="wf-in mt-1.5" type="number" value={cfg.sector_cap ?? ""} placeholder="none" onChange={(e) => upd(["sector_cap"], e.target.value === "" ? null : parseInt(e.target.value))} /></Field>
            </div>
          </Card>

          {/* Exits */}
          <Card className="p-5">
            <SectionTitle dot="#f4855f">Exits</SectionTitle>
            <Field label="Stop loss">
              <select className="wf-in mt-1.5" value={cfg.stop_loss.type} onChange={(e) => upd(["stop_loss", "type"], e.target.value)}>
                <option value="none">None</option><option value="pct">Percent</option><option value="atr">ATR multiple</option><option value="trailing">Trailing ATR</option>
              </select>
            </Field>
            {(cfg.stop_loss.type === "atr" || cfg.stop_loss.type === "trailing") && (
              <><div className="flex items-center justify-between mt-3.5"><span className="text-[12.5px] font-bold text-muted">Stop ATR ×</span><span className="text-[18px] font-extrabold">{cfg.stop_loss.mult ?? 2}</span></div>
                <Slider value={cfg.stop_loss.mult ?? 2} min={0.5} max={5} step={0.1} onChange={(v) => upd(["stop_loss", "mult"], v)} /></>
            )}
            {cfg.stop_loss.type === "pct" && (
              <Field label="Stop %"><input className="wf-in mt-1.5" type="number" step="0.01" value={cfg.stop_loss.value ?? 0.15} onChange={(e) => upd(["stop_loss", "value"], parseFloat(e.target.value))} /></Field>
            )}
            <Field label="Take profit"><select className="wf-in mt-1.5" value={cfg.take_profit.type} onChange={(e) => upd(["take_profit", "type"], e.target.value)}><option value="none">None</option><option value="pct">Percent</option><option value="r_multiple">R multiple</option></select></Field>
            {cfg.take_profit.type === "r_multiple" && (
              <><div className="flex items-center justify-between mt-3.5"><span className="text-[12.5px] font-bold text-muted">Target R</span><span className="text-[18px] font-extrabold">{cfg.take_profit.r ?? 2}</span></div>
                <Slider value={cfg.take_profit.r ?? 2} min={1} max={5} step={0.5} onChange={(v) => upd(["take_profit", "r"], v)} /></>
            )}
            <Field label="Max hold (days)"><input className="wf-in mt-1.5" type="number" value={cfg.max_hold_days ?? ""} placeholder="none" onChange={(e) => upd(["max_hold_days"], e.target.value === "" ? null : parseInt(e.target.value))} /></Field>
          </Card>

          {/* Regime */}
          <Card className="p-5">
            <SectionTitle dot="#f7b9dd">Regime filter</SectionTitle>
            <div className="flex items-center justify-between p-3 rounded-xl" style={{ background: "#f7f5fc" }}>
              <div><div className="text-[13px] font-bold">Enabled</div><div className="text-[11.5px] text-faint">Scale to cash below index MA</div></div>
              <Switch on={cfg.regime_filter.enabled} onClick={() => upd(["regime_filter", "enabled"], !cfg.regime_filter.enabled)} />
            </div>
            <Field label="MA period"><input className="wf-in mt-1.5" type="number" value={cfg.regime_filter.ma_period} onChange={(e) => upd(["regime_filter", "ma_period"], parseInt(e.target.value) || 200)} /></Field>
            <div className="mt-4"><span className="text-[12px] font-bold text-muted">Mode</span>
              <Segmented value={cfg.regime_filter.mode} onChange={(v) => upd(["regime_filter", "mode"], v)} options={[{ value: "binary", label: "Binary" }, { value: "scale", label: "Scale" }]} />
            </div>
          </Card>

          {/* Costs & period */}
          <Card className="p-5">
            <SectionTitle dot="#c4b6f7">Costs &amp; period</SectionTitle>
            <span className="text-[12px] font-bold text-muted">Costs (bps / side)</span>
            <div className="grid grid-cols-3 gap-2 mt-1.5">
              <Field label="Brokerage"><input className="wf-in mt-1" type="number" value={cfg.costs_bps.brokerage} onChange={(e) => upd(["costs_bps", "brokerage"], parseFloat(e.target.value) || 0)} /></Field>
              <Field label="STT"><input className="wf-in mt-1" type="number" value={cfg.costs_bps.stt} onChange={(e) => upd(["costs_bps", "stt"], parseFloat(e.target.value) || 0)} /></Field>
              <Field label="Slippage"><input className="wf-in mt-1" type="number" value={cfg.costs_bps.slippage} onChange={(e) => upd(["costs_bps", "slippage"], parseFloat(e.target.value) || 0)} /></Field>
            </div>
            <div className="mt-3.5"><span className="text-[12px] font-bold text-muted">Rebalance</span>
              <select className="wf-in mt-1.5" value={cfg.rebalance} onChange={(e) => upd(["rebalance"], e.target.value)}>
                {FREQUENCIES.map((f) => <option key={f} value={f}>{f[0].toUpperCase() + f.slice(1)}</option>)}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-2 mt-3.5">
              <Field label="Start"><input className="wf-in mt-1.5" type="date" value={cfg.start} onChange={(e) => upd(["start"], e.target.value)} /></Field>
              <Field label="End"><input className="wf-in mt-1.5" type="date" value={cfg.end ?? ""} onChange={(e) => upd(["end"], e.target.value)} /></Field>
            </div>
            <Field label="Benchmark"><select className="wf-in mt-1.5" value={cfg.benchmark} onChange={(e) => upd(["benchmark"], e.target.value)}>{BENCHMARKS.map((b) => <option key={b.value} value={b.value}>{b.label}</option>)}</select></Field>
          </Card>
        </div>

        {/* ── JSON PANE + actions ── */}
        <div className="lg:sticky lg:top-5 space-y-3.5 animate-rise">
          {readiness && (
            <Card className="px-4 py-3" style={{ background: readiness.verdict.includes("backtest") ? "#eef6dd" : "#fff3da" }}>
              <div className="text-[11.5px] font-extrabold uppercase tracking-wide" style={{ color: readiness.verdict.includes("backtest") ? "#5b6b1f" : "#9a6c12" }}>Readiness · {readiness.verdict}</div>
              <div className="text-[12px] text-ink/80 mt-1">{readiness.summary}</div>
            </Card>
          )}
          <Card style={{ background: "#16151c", padding: "18px 20px" }}>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2.5"><span className="w-2.5 h-2.5 rounded-full" style={{ background: "#c4e05a", boxShadow: "0 0 8px #c4e05a" }} /><span className="text-white font-bold text-[14px]">Live config</span></div>
              <span className="font-mono text-[11px]" style={{ color: "#6f6b82" }}>strategy.json</span>
            </div>
            <JsonView value={fullCfg} />
            <div className="flex gap-2 mt-3.5">
              <button className="btn flex-1" style={{ background: "#26252e", color: "#eceaf2" }} disabled={!!busy} onClick={save}>{busy === "save" ? "saving…" : "Save"}</button>
              <button className="btn btn-acc flex-[1.4]" disabled={!!busy} onClick={run}>{busy === "run" ? "running…" : "Run backtest →"}</button>
            </div>
            {msg && <div className="text-[12px] mt-2.5" style={{ color: "#cdbcff" }}>{msg}</div>}
          </Card>
          <SweepPanel config={fullCfg} onSaved={(id) => router.push(`/strategies/${id}`)} />
        </div>
      </div>
    </div>
  );
}

// ── filter chip builder (indicator + operator + value, with free-text escape) ──
function FilterBuilder({ label, placeholder, list, onChange }:
  { label: string; placeholder: string; list: string[]; onChange: (l: string[]) => void }) {
  const [tok, setTok] = useState("close");
  const [op, setOp] = useState(">=");
  const [val, setVal] = useState("");
  const [raw, setRaw] = useState("");
  const add = () => { if (!val.trim()) return; onChange([...list, `${tok} ${op} ${val.trim()}`]); setVal(""); };
  const addRaw = () => { if (!raw.trim()) return; onChange([...list, raw.trim()]); setRaw(""); };
  return (
    <div>
      <span className="text-[12px] font-bold text-muted">{label}</span>
      <div className="flex flex-wrap gap-1.5 mt-2 mb-2">
        {list.map((f, i) => (
          <span key={i} className="wf-chip">{f}<button onClick={() => onChange(list.filter((_, j) => j !== i))}>×</button></span>
        ))}
        {list.length === 0 && <span className="text-[12px] text-faint">none yet</span>}
      </div>
      <div className="flex gap-1.5">
        <FactorSelect value={tok} onChange={setTok} compact />
        <select className="wf-in" style={{ width: 64 }} value={op} onChange={(e) => setOp(e.target.value)}>{OPERATORS.map((o) => <option key={o}>{o}</option>)}</select>
        <input className="wf-in" style={{ width: 90 }} placeholder="value" value={val} onChange={(e) => setVal(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} />
        <button className="btn btn-ink" style={{ borderRadius: 11 }} onClick={add}>Add</button>
      </div>
      <div className="flex gap-1.5 mt-1.5">
        <input className="wf-in" placeholder={`or type a raw expression — ${placeholder}`} value={raw} onChange={(e) => setRaw(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addRaw()} />
        <button className="btn btn-ghost" style={{ borderRadius: 11 }} onClick={addRaw}>+ raw</button>
      </div>
    </div>
  );
}

function FactorSelect({ value, onChange, compact = false }: { value: string; onChange: (v: string) => void; compact?: boolean }) {
  return (
    <select className="wf-in" style={compact ? { flex: 1, minWidth: 0 } : { marginTop: 6 }} value={QUICK.includes(value) ? value : "__custom"} onChange={(e) => e.target.value !== "__custom" && onChange(e.target.value)}>
      {QUICK.map((q) => {
        const f = FACTOR_BY_TOKEN[q] || FACTOR_BY_TOKEN[q.replace(/\d+$/, "{N}")];
        const so = f?.survivorsOnly ? " ⚠" : "";
        return <option key={q} value={q}>{q}{so}</option>;
      })}
      {!QUICK.includes(value) && <option value="__custom">{value} (custom)</option>}
    </select>
  );
}

// ── explore variations (parameter sweep) ──
function SweepPanel({ config, onSaved }: { config: StrategyConfig; onSaved: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [grid, setGrid] = useState<Record<string, string>>({ n_holdings: "8, 10, 15, 20", "stop_loss.mult": "1.5, 2, 2.5, 3" });
  const [metric, setMetric] = useState("sharpe");
  const [res, setRes] = useState<SweepResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function runSweep() {
    setBusy(true); setErr(null); setRes(null);
    const g: Record<string, unknown[]> = {};
    for (const [k, v] of Object.entries(grid)) {
      const parts = v.split(",").map((s) => s.trim()).filter(Boolean);
      if (!parts.length) continue;
      g[k] = parts.map((p) => (isNaN(Number(p)) ? p : Number(p)));
    }
    try { setRes(await api.sweep(config, g, metric)); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }
  async function saveRow(overrides: Record<string, unknown>, rank: number) {
    const merged = applyOverrides(config, overrides);
    const s = await api.saveStrategy(`${config.name}_v${rank}`, merged);
    await api.runBacktest(merged, s.id, true);
    onSaved(s.id);
  }

  return (
    <Card className="px-4 py-3">
      <button className="flex items-center gap-2 text-[13px] font-extrabold" onClick={() => setOpen(!open)}>
        <span className="text-faint">{open ? "▾" : "▸"}</span> Explore variations
        <span className="text-[11.5px] text-faint font-medium">— auto-run a grid &amp; rank</span>
      </button>
      {open && (
        <div className="mt-3 space-y-2.5">
          {["n_holdings", "stop_loss.mult", "rebalance"].map((p) => (
            <div key={p} className="flex items-center gap-2">
              <span className="text-[12px] font-mono text-muted" style={{ width: 110 }}>{p}</span>
              <input className="wf-in" placeholder="comma values e.g. 8, 10, 15" value={grid[p] || ""} onChange={(e) => setGrid({ ...grid, [p]: e.target.value })} />
            </div>
          ))}
          <div className="flex items-center gap-2">
            <select className="wf-in" style={{ width: 130 }} value={metric} onChange={(e) => setMetric(e.target.value)}>
              <option value="sharpe">rank by sharpe</option><option value="cagr">rank by CAGR</option><option value="sortino">rank by sortino</option>
            </select>
            <button className="btn btn-ink flex-1" style={{ borderRadius: 11 }} disabled={busy} onClick={runSweep}>{busy ? "running grid…" : "Run sweep"}</button>
          </div>
          {err && <div className="text-[12px] text-loss">{err}</div>}
          {res && (
            <div className="rounded-xl overflow-hidden bg-white">
              <div className="grid px-3 py-2 text-[11px] text-faint font-bold border-b" style={{ gridTemplateColumns: "1.6fr .7fr .7fr .7fr .8fr", borderColor: "#f0eef6" }}>
                <span>Variant</span><span className="text-right">CAGR</span><span className="text-right">DD</span><span className="text-right">Sharpe</span><span></span>
              </div>
              <div className="scroll-y" style={{ maxHeight: 240 }}>
                {res.ranked.filter((r) => r.summary).slice(0, 30).map((r, i) => (
                  <div key={i} className="wf-row grid px-3 py-2 text-[12px] items-center tn border-b" style={{ gridTemplateColumns: "1.6fr .7fr .7fr .7fr .8fr", borderColor: "#f6f4fb" }}>
                    <span className="font-mono text-[11px] text-muted truncate">{Object.entries(r.overrides).map(([k, v]) => `${k.split(".").pop()}=${v}`).join(" ") || "base"}</span>
                    <span className="text-right text-gain font-bold">{pctSigned(r.summary!.cagr)}</span>
                    <span className="text-right text-loss">{pctSigned(r.summary!.max_drawdown)}</span>
                    <span className="text-right">{num(r.summary!.sharpe)}</span>
                    <span className="text-right"><button className="text-[11px] font-bold px-2 py-1 rounded-full" style={{ border: "1.5px solid #c4e05a", background: "#f2fae0", color: "#3f7d1c" }} onClick={() => saveRow(r.overrides, i + 1)}>save</button></span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function applyOverrides(base: StrategyConfig, ov: Record<string, unknown>): StrategyConfig {
  let c: any = JSON.parse(JSON.stringify(base));
  for (const [path, val] of Object.entries(ov)) c = set(c, path.split("."), val);
  return c;
}
