"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Readiness, StrategyConfig } from "@/lib/types";
import { ALL_FACTORS, OPERATORS, FREQUENCIES, BENCHMARKS, defaultConfig, survivorsOnly } from "@/lib/catalog";
import { Card, Field, Switch, Segmented, Slider, SectionTitle, Pill } from "@/components/ui";
import { JsonView } from "@/components/JsonView";

// curated ready-to-use tokens for the pickers (own-DVM removed iter-31 — raw fundamentals + tl_DVM remain)
const QUICK = [
  "close", "open", "high", "low", "adtv_cr",
  "sma50", "sma100", "sma200", "ema50", "ema200",
  "roc21", "roc63", "roc126", "roc252", "rsi14", "atr14", "adx14",
  "dist_high252", "rel_strength126",
  "roe", "roa", "opm", "np_qtr_yoy", "pe", "pb",
  "tl_durability", "tl_valuation", "tl_momentum", "tl_pe", "tl_peg", "tl_pbv", "tl_roe", "tl_roce", "tl_de",
  "piotroski", "promoter_pledge", "eps_growth",
];
const FACTOR_BY_TOKEN = Object.fromEntries(ALL_FACTORS.map((f) => [f.token, f]));

function set(obj: any, path: string[], val: any) {
  const o = { ...obj }; let cur = o;
  for (let i = 0; i < path.length - 1; i++) { cur[path[i]] = { ...cur[path[i]] }; cur = cur[path[i]]; }
  cur[path[path.length - 1]] = val; return o;
}

export function StrategyBuilder({ initial }: { initial?: { id?: string; name: string; config: StrategyConfig } }) {
  const router = useRouter();
  const [cfg, setCfg] = useState<StrategyConfig>(initial?.config || defaultConfig());
  const [name, setName] = useState(initial?.name ?? "Untitled strategy");
  const [sid, setSid] = useState<string | null>(initial?.id || null);
  const [rankMode, setRankMode] = useState<"single" | "composite">((initial?.config?.rank_blend?.length ?? 0) > 0 ? "composite" : "single");
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const upd = (path: string[], v: any) => setCfg((c) => set(c, path, v));
  const sv = useMemo(() => survivorsOnly(cfg), [cfg]);
  const fullCfg = useMemo(() => ({ ...cfg, name }), [cfg, name]);

  // Merged filters: the engine ANDs universe.filters + entry_filters anyway, so we show ONE list and
  // write it all to universe.filters (clearing entry_filters) — no behaviour change, less confusion.
  const filters = useMemo(() => [...(cfg.universe.filters || []), ...(cfg.entry_filters || [])], [cfg]);
  const setFilters = (l: string[]) =>
    setCfg((c) => ({ ...c, universe: { ...c.universe, filters: l }, entry_filters: [] }));

  // Client-side guardrails — instant inline feedback mirroring the server validators.
  const errs = useMemo(() => {
    const e: string[] = [];
    if (!name.trim()) e.push("Name your strategy.");
    const blend = cfg.rank_blend || [];
    if (blend.length > 0) {
      if (blend.some((r) => !r.factor)) e.push("Pick a factor for every composite-ranking row.");
      if (blend.reduce((s, r) => s + (r.weight || 0), 0) !== 100) e.push("Composite ranking weights must total 100%.");
    } else if (!cfg.rank_by?.trim()) {
      e.push("Pick a “Sort by” variable (or write an expression).");
    }
    if (cfg.end && cfg.start && cfg.end <= cfg.start) e.push("End date must be after start date.");
    if (cfg.capital < 1000) e.push("Capital must be at least ₹1,000.");
    if (cfg.max_weight_per_stock != null && !(cfg.max_weight_per_stock > 0 && cfg.max_weight_per_stock <= 1))
      e.push("Max weight / stock must be between 0 and 100%.");
    if (cfg.max_hold_days != null && cfg.max_hold_days < 1) e.push("Max hold days must be at least 1.");
    if (cfg.sector_cap != null && cfg.sector_cap < 1) e.push("Sector cap must be at least 1.");
    return e;
  }, [name, cfg]);

  const capWarn = (cfg.max_weight_per_stock != null && cfg.max_weight_per_stock > 0
    && cfg.max_weight_per_stock * cfg.n_holdings < 1)
    ? `${Math.round(cfg.max_weight_per_stock * 100)}% cap × ${cfg.n_holdings} holdings = ${Math.round(cfg.max_weight_per_stock * cfg.n_holdings * 100)}% invested — the rest sits in cash.`
    : null;

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
  const blocked = !!busy || errs.length > 0;

  return (
    <div>
      {busy === "run" && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(16,15,23,.55)", backdropFilter: "blur(2px)" }}>
          <div className="wf-card px-7 py-6 text-center" style={{ background: "#fff" }}>
            <div className="wf-spinner mx-auto mb-3" />
            <div className="font-extrabold text-[15px]">Running backtest…</div>
            <div className="text-[12px] text-faint mt-1">Screening, ranking and simulating across the window.</div>
          </div>
        </div>
      )}
      <div className="flex items-end justify-between mt-6 mb-4 animate-rise">
        <div className="w-full">
          <div className="text-[13px] text-faint font-bold uppercase tracking-wide">Strategy builder</div>
          <div className="flex items-center gap-2 mt-1.5 max-w-[640px]">
            <input className="bg-transparent text-[34px] font-extrabold tracking-tight outline-none w-full border-b-2 border-dashed pb-0.5 transition-colors focus:border-solid"
              style={{ borderColor: name ? "#e3dff0" : "#cdaaff" }} maxLength={100}
              placeholder="Name your strategy…" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
        </div>
      </div>

      <div className="grid lg:grid-cols-[1.65fr_1fr] gap-4 items-start">
        {/* ── FORM (single column — A-BLD-2: no neighbour reflow) ── */}
        <div className="grid grid-cols-1 gap-3.5 min-w-0">
          {/* Universe & filters (merged) */}
          <Card className="p-5">
            <SectionTitle dot="#a9c9f2">Universe &amp; filters</SectionTitle>
            <FilterBuilder label="Filters — every condition must pass for a stock to qualify"
              placeholder="raw expression, e.g. close > sma200 & roc126 > 0"
              list={filters} onChange={setFilters} />
            <div className="flex items-center justify-between mt-3 pt-3 border-t" style={{ borderColor: "#f0eef6" }}>
              <span className="text-[12px] text-muted">Universe coverage</span>
              {sv.survivorsOnly
                ? <Pill tone="warn">Survivors-only · {sv.offenders.join(", ")}</Pill>
                : <Pill tone="good">✓ Survivorship-free</Pill>}
            </div>
          </Card>

          {/* Ranking */}
          <Card className="p-5">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2.5">
                <span className="w-[11px] h-[11px] rounded" style={{ background: "#b9d24a" }} />
                <span className="font-extrabold text-[15px]">Ranking</span>
              </div>
              <div className="flex gap-0.5 p-0.5 rounded-lg" style={{ background: "#f1eef8" }}>
                {(["single", "composite"] as const).map((m) => (
                  <button key={m} className="wf-seg" data-active={rankMode === m ? "1" : "0"} style={{ padding: "6px 12px", fontSize: 12 }}
                    onClick={() => {
                      if (m === rankMode) return;
                      setRankMode(m);
                      if (m === "single") upd(["rank_blend"], []);
                      else if (!(cfg.rank_blend && cfg.rank_blend.length)) upd(["rank_blend"], [{ factor: cfg.rank_by || "tl_momentum", weight: 100, order: cfg.rank_order }]);
                    }}>{m === "single" ? "Single" : "Composite"}</button>
                ))}
              </div>
            </div>
            {rankMode === "single" ? (
              <div className="grid grid-cols-[1.4fr_1fr] gap-3.5 items-start">
                <RankInput value={cfg.rank_by} onChange={(v) => upd(["rank_by"], v)} />
                <div>
                  <span className="text-[12px] font-bold text-muted">Order</span>
                  <Segmented value={cfg.rank_order} onChange={(v) => upd(["rank_order"], v)}
                    options={[{ value: "desc", label: "Max first" }, { value: "asc", label: "Min first" }]} />
                </div>
              </div>
            ) : (
              <>
                <div className="text-[12px] text-muted mb-2.5">Weighted blend of up to 5 factors — names are ranked by the weighted percentile score (weights must total 100).</div>
                <RankBlend rows={cfg.rank_blend || []} onChange={(r) => upd(["rank_blend"], r)} />
              </>
            )}
          </Card>

          {/* Sizing */}
          <Card className="p-5">
            <SectionTitle dot="#f5e049">Position sizing</SectionTitle>
            <div className="flex items-center justify-between"><span className="text-[12.5px] font-bold text-muted">Holdings</span><span className="text-[20px] font-extrabold">{cfg.n_holdings}</span></div>
            <Slider value={cfg.n_holdings} min={3} max={50} onChange={(v) => upd(["n_holdings"], v)} />
            <div className="flex justify-between text-[10.5px] text-faint mt-0.5"><span>3</span><span>50</span></div>
            <div className="mt-4"><span className="text-[12px] font-bold text-muted">Weighting</span>
              <Segmented value={cfg.weighting} onChange={(v) => upd(["weighting"], v)}
                options={[{ value: "equal", label: "Equal" }, { value: "inverse_vol", label: "Inverse-vol" }]} />
            </div>
            <div className="flex items-center justify-between mt-4 p-3 rounded-xl" style={{ background: "#f7f5fc" }}>
              <div><div className="text-[13px] font-bold">Invest fully</div><div className="text-[11.5px] text-faint">No idle-cash drag</div></div>
              <Switch on={cfg.invest_fully} onClick={() => upd(["invest_fully"], !cfg.invest_fully)} />
            </div>
            <div className="grid grid-cols-2 gap-3 mt-3.5">
              <Field label="Max weight / stock (%)"><input className="wf-in mt-1.5" type="number" step="1" min="0" max="100" value={cfg.max_weight_per_stock != null ? Math.round(cfg.max_weight_per_stock * 100) : ""} placeholder="none" onChange={(e) => upd(["max_weight_per_stock"], e.target.value === "" ? null : parseFloat(e.target.value) / 100)} /></Field>
              <Field label="Sector cap (stocks)"><input className="wf-in mt-1.5" type="number" min="1" value={cfg.sector_cap ?? ""} placeholder="none" onChange={(e) => upd(["sector_cap"], e.target.value === "" ? null : parseInt(e.target.value))} /></Field>
            </div>
            {capWarn && <div className="text-[11px] mt-2" style={{ color: "#9a6c12" }}>⚠ {capWarn}</div>}
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
              <Field label="Stop % (fraction, 0–1)"><input className="wf-in mt-1.5" type="number" step="0.01" min="0.01" max="0.99" value={cfg.stop_loss.value ?? 0.15} onChange={(e) => upd(["stop_loss", "value"], parseFloat(e.target.value))} /></Field>
            )}
            <Field label="Take profit"><select className="wf-in mt-1.5" value={cfg.take_profit.type} onChange={(e) => upd(["take_profit", "type"], e.target.value)}><option value="none">None</option><option value="pct">Percent</option><option value="r_multiple">R multiple</option></select></Field>
            {cfg.take_profit.type === "r_multiple" && (
              <><div className="flex items-center justify-between mt-3.5"><span className="text-[12.5px] font-bold text-muted">Target R</span><span className="text-[18px] font-extrabold">{cfg.take_profit.r ?? 2}</span></div>
                <Slider value={cfg.take_profit.r ?? 2} min={1} max={5} step={0.5} onChange={(v) => upd(["take_profit", "r"], v)} /></>
            )}
            <Field label="Max hold (days)"><input className="wf-in mt-1.5" type="number" min="1" value={cfg.max_hold_days ?? ""} placeholder="none" onChange={(e) => upd(["max_hold_days"], e.target.value === "" ? null : parseInt(e.target.value))} /></Field>
          </Card>

          {/* Regime */}
          <Card className="p-5">
            <SectionTitle dot="#f7b9dd">Regime filter</SectionTitle>
            <div className="flex items-center justify-between p-3 rounded-xl" style={{ background: "#f7f5fc" }}>
              <div><div className="text-[13px] font-bold">Enabled</div><div className="text-[11.5px] text-faint">Scale to cash when the index is below its MA</div></div>
              <Switch on={cfg.regime_filter.enabled} onClick={() => upd(["regime_filter", "enabled"], !cfg.regime_filter.enabled)} />
            </div>
            {cfg.regime_filter.enabled && (
              <>
                <Field label="MA period"><input className="wf-in mt-1.5" type="number" min="1" value={cfg.regime_filter.ma_period} onChange={(e) => upd(["regime_filter", "ma_period"], parseInt(e.target.value) || 200)} /></Field>
                <div className="mt-4"><span className="text-[12px] font-bold text-muted">Mode</span>
                  <Segmented value={cfg.regime_filter.mode} onChange={(v) => upd(["regime_filter", "mode"], v)} options={[{ value: "binary", label: "Binary (cash)" }, { value: "scale", label: "Scale" }]} />
                </div>
              </>
            )}
          </Card>

          {/* Costs & period */}
          <Card className="p-5">
            <SectionTitle dot="#c4b6f7">Costs &amp; period</SectionTitle>
            <div className="rounded-xl p-3 text-[12px]" style={{ background: "#f7f5fc" }}>
              <div className="font-bold text-[12.5px]">NSE delivery costs · fixed</div>
              <div className="text-faint mt-1">≈11.9 bps buy · ≈10.4 bps sell · +₹15.93 DP/sell · ₹0 brokerage · no slippage</div>
              <div className="text-faint mt-1">Stress them with the Cost-sensitivity card on the result page.</div>
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
            {cfg.end && cfg.start && cfg.end <= cfg.start && <div className="text-[11px] text-loss mt-1">End date must be after start date.</div>}
            <Field label="Benchmark"><select className="wf-in mt-1.5" value={cfg.benchmark} onChange={(e) => upd(["benchmark"], e.target.value)}>{BENCHMARKS.map((b) => <option key={b.value} value={b.value}>{b.label}</option>)}</select></Field>
            <Field label={`Capital (₹)  ·  ≈ ${(cfg.capital / 1e5).toFixed(2)} L`}>
              <input className="wf-in mt-1.5" type="number" step="50000" min="1000" value={cfg.capital} onChange={(e) => upd(["capital"], parseFloat(e.target.value) || 0)} />
            </Field>
          </Card>
        </div>

        {/* ── JSON PANE + actions ── */}
        <div className="lg:sticky lg:top-5 space-y-3.5 animate-rise min-w-0">
          <Card style={{ background: "#16151c", padding: "18px 20px" }}>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2.5"><span className="w-2.5 h-2.5 rounded-full" style={{ background: "#c4e05a", boxShadow: "0 0 8px #c4e05a" }} /><span className="text-white font-bold text-[14px]">Live config</span></div>
              <span className="font-mono text-[11px]" style={{ color: "#6f6b82" }}>strategy.json</span>
            </div>
            <JsonView value={fullCfg} />
            <div className="flex gap-2 mt-3.5">
              <button className="btn flex-1" style={{ background: "#26252e", color: "#eceaf2" }} disabled={blocked} onClick={save}>{busy === "save" ? "saving…" : "Save"}</button>
              <button className="btn btn-acc flex-[1.4]" disabled={blocked} onClick={run}>{busy === "run" ? "running…" : "Run backtest →"}</button>
            </div>
            {readiness && errs.length === 0 && (
              <div className="mt-2.5 text-[11.5px] font-semibold" style={{ color: readiness.verdict === "invalid" ? "#ff9ec4" : "#c8f08a" }}>
                {readiness.verdict === "invalid" ? `Invalid — ${readiness.summary}` : `Ready · ${readiness.summary}`}
              </div>
            )}
            {errs.length > 0 && <div className="mt-2.5 rounded-lg px-3 py-2 text-[12px] font-semibold" style={{ background: "#3a2230", color: "#ffadcb" }}>Fix to continue: {errs[0]}</div>}
            {msg && <div className="mt-2.5 rounded-lg px-3 py-2 text-[12px] font-semibold" style={{ background: msg.includes("fail") ? "#3a2230" : "#23302a", color: msg.includes("fail") ? "#ffadcb" : "#c8f08a" }}>{msg}</div>}
          </Card>
        </div>
      </div>
    </div>
  );
}

// ── filter builder: Builder dropdown OR Raw expression (one at a time) ──
function FilterBuilder({ label, placeholder, list, onChange }:
  { label: string; placeholder: string; list: string[]; onChange: (l: string[]) => void }) {
  const [mode, setMode] = useState<"builder" | "raw">("builder");
  const [tok, setTok] = useState("");
  const [op, setOp] = useState(">=");
  const [val, setVal] = useState("");
  const [raw, setRaw] = useState("");
  const [err, setErr] = useState("");
  const add = () => {
    if (!tok) { setErr("Pick a variable."); return; }
    if (val.trim() === "" || Number.isNaN(Number(val))) { setErr("Value must be a number."); return; }
    setErr(""); onChange([...list, `${tok} ${op} ${val.trim()}`]); setVal("");
  };
  const addRaw = () => { if (!raw.trim()) return; onChange([...list, raw.trim()]); setRaw(""); };
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="text-[12px] font-bold text-muted">{label}</span>
        <div className="flex gap-0.5 p-0.5 rounded-lg" style={{ background: "#f1eef8" }}>
          {(["builder", "raw"] as const).map((m) => (
            <button key={m} className="wf-seg" data-active={mode === m ? "1" : "0"} style={{ padding: "6px 12px", fontSize: 12 }} onClick={() => setMode(m)}>{m === "builder" ? "Builder" : "Raw"}</button>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5 mt-2 mb-2">
        {list.map((f, i) => (
          <span key={i} className="wf-chip">{f}<button onClick={() => onChange(list.filter((_, j) => j !== i))}>×</button></span>
        ))}
        {list.length === 0 && <span className="text-[12px] text-faint">none yet</span>}
      </div>
      {mode === "builder" ? (
        <div className="flex gap-1.5">
          <FactorSelect value={tok} onChange={(v) => { setTok(v); setErr(""); }} compact />
          <select className="wf-in" style={{ width: 64 }} value={op} onChange={(e) => setOp(e.target.value)}>{OPERATORS.map((o) => <option key={o}>{o}</option>)}</select>
          <input className="wf-in" style={{ width: 90 }} placeholder="value" value={val} onChange={(e) => { setVal(e.target.value); setErr(""); }} onKeyDown={(e) => e.key === "Enter" && add()} />
          <button className="btn btn-ink" style={{ borderRadius: 11 }} onClick={add}>Add</button>
        </div>
      ) : (
        <div>
          <div className="flex gap-1.5">
            <input className="wf-in" style={{ minWidth: 0 }} placeholder={placeholder} value={raw} onChange={(e) => setRaw(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addRaw()} />
            <button className="btn btn-ink" style={{ borderRadius: 11 }} onClick={addRaw}>Add</button>
          </div>
          <div className="text-[11px] text-faint mt-1.5">
            Use <span className="font-mono">&amp;</span> / <span className="font-mono">|</span> to combine, chained compares (<span className="font-mono">50 &lt; rsi14 &lt; 80</span>), arithmetic — e.g. <span className="font-mono">close &gt; sma200 &amp; roc126 &gt; 0</span>.
          </div>
        </div>
      )}
      {err && <div className="text-[11px] text-loss mt-1">{err}</div>}
    </div>
  );
}

// ── rank input: a single variable, or a derived expression ──
function RankInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [mode, setMode] = useState<"builder" | "raw">(value && !QUICK.includes(value) ? "raw" : "builder");
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="text-[12px] font-bold text-muted">Sort by</span>
        <div className="flex gap-0.5 p-0.5 rounded-lg" style={{ background: "#f1eef8" }}>
          {(["builder", "raw"] as const).map((m) => (
            <button key={m} className="wf-seg" data-active={mode === m ? "1" : "0"} style={{ padding: "6px 12px", fontSize: 12 }} onClick={() => setMode(m)}>{m === "builder" ? "Variable" : "Expression"}</button>
          ))}
        </div>
      </div>
      {mode === "builder"
        ? <FactorSelect value={value} onChange={onChange} />
        : <>
          <input className="wf-in mt-1.5" placeholder="e.g. roc126 / atr14" value={value} onChange={(e) => onChange(e.target.value)} />
          <span className="block text-[11px] text-faint mt-1">Any expression — combine factors &amp; arithmetic; names are ranked by the result.</span>
        </>}
    </div>
  );
}

// ── composite ranking: weighted blend of up to 5 factors (writes cfg.rank_blend) ──
function RankBlend({ rows, onChange }:
  { rows: NonNullable<StrategyConfig["rank_blend"]>; onChange: (r: NonNullable<StrategyConfig["rank_blend"]>) => void }) {
  const total = rows.reduce((s, r) => s + (r.weight || 0), 0);
  const updRow = (i: number, patch: Partial<{ factor: string; weight: number; order: "desc" | "asc" }>) =>
    onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="space-y-2">
      {rows.map((r, i) => (
        <div key={i} className="flex gap-1.5 items-center">
          <div className="flex-1 min-w-0"><FactorSelect value={r.factor} onChange={(v) => updRow(i, { factor: v })} compact /></div>
          <input className="wf-in" style={{ width: 74 }} type="number" min="0" max="100" value={r.weight}
            onChange={(e) => updRow(i, { weight: e.target.value === "" ? 0 : parseFloat(e.target.value) })} placeholder="wt %" />
          <div className="flex gap-0.5 p-0.5 rounded-lg" style={{ background: "#f1eef8" }}>
            {(["desc", "asc"] as const).map((o) => (
              <button key={o} className="wf-seg" data-active={r.order === o ? "1" : "0"} style={{ padding: "6px 9px", fontSize: 11 }} onClick={() => updRow(i, { order: o })}>{o === "desc" ? "Max" : "Min"}</button>
            ))}
          </div>
          <button className="wf-menubtn" style={{ width: 32, height: 32, fontSize: 16 }} title="Remove factor"
            disabled={rows.length <= 1} onClick={() => onChange(rows.filter((_, j) => j !== i))}>×</button>
        </div>
      ))}
      <div className="flex items-center justify-between pt-1">
        <button className="btn btn-ghost" style={{ padding: "6px 12px" }} disabled={rows.length >= 5}
          onClick={() => onChange([...rows, { factor: "", weight: 0, order: "desc" }])}>+ Add factor</button>
        <span className="text-[12px] font-bold" style={{ color: total === 100 ? "#1f7a4d" : "#c23e74" }}>
          Total {total}%{total === 100 ? " ✓" : " — must be 100"}
        </span>
      </div>
    </div>
  );
}

function FactorSelect({ value, onChange, compact = false, placeholder = "— pick a variable —" }:
  { value: string; onChange: (v: string) => void; compact?: boolean; placeholder?: string }) {
  const known = QUICK.includes(value);
  return (
    <select className="wf-in" style={compact ? { flex: 1, minWidth: 0 } : { marginTop: 6 }}
      value={known ? value : value ? "__custom" : ""}
      onChange={(e) => { if (e.target.value !== "__custom") onChange(e.target.value); }}>
      <option value="" disabled>{placeholder}</option>
      {QUICK.map((q) => {
        const f = FACTOR_BY_TOKEN[q] || FACTOR_BY_TOKEN[q.replace(/\d+$/, "{N}")];
        const so = f?.survivorsOnly ? " ⚠" : "";
        return <option key={q} value={q}>{q}{so}</option>;
      })}
      {!known && value && <option value="__custom">{value} (custom)</option>}
    </select>
  );
}
