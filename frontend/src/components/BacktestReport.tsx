"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { BacktestResultFull, CostSensitivity, StrategyConfig, SweepResult } from "@/lib/types";
import { api } from "@/lib/api";
import { pct, pctSigned, num, moneyCompact, signClass } from "@/lib/format";
import { survivorsOnly } from "@/lib/catalog";
import { MetricCard, MetricMini, Card, Pill, useReveal } from "@/components/ui";
import { EquityChart, DrawdownChart } from "@/components/charts";

// Human-readable rank description — handles both single rank_by and composite rank_blend.
function rankDesc(c: StrategyConfig): string {
  const blend = c.rank_blend ?? [];
  if (blend.length) return "composite — " + blend.map((r) => `${r.factor} ${r.weight}%${r.order === "asc" ? "↑" : "↓"}`).join(" · ");
  return `${c.rank_by || "—"} ${c.rank_order === "asc" ? "↑ (min first)" : "↓ (max first)"}`;
}

const EXIT_TONE: Record<string, string> = {
  target: "good", stop: "bad", time: "warn", delisted: "neutral", rebalance: "neutral", end: "neutral",
};

export function BacktestReport({ res, config }: { res: BacktestResultFull; config?: StrategyConfig }) {
  const s = res.summary;
  const ref = useReveal();
  const sv = config ? survivorsOnly(config) : { survivorsOnly: false, offenders: [] };
  const [showNotes, setShowNotes] = useState(false);

  return (
    <div className="space-y-3.5">
      {/* consolidated, labeled config home (B-RES-CONFIG) — single structured place, no mono one-liner */}
      {config && (
        <Card className="px-5 py-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[13px] font-extrabold text-muted">Configuration</span>
            <Pill tone={sv.survivorsOnly ? "warn" : "good"}>{sv.survivorsOnly ? "SURVIVORS-ONLY" : "SURVIVORSHIP-FREE"}</Pill>
          </div>
          <ConfigGrid c={config} sv={sv} />
        </Card>
      )}

      {/* big metric cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5">
        <MetricCard tone="lime" label="CAGR" delay={0}
          value={<span className={signClass(s.cagr)}>{pctSigned(s.cagr)}</span>}
          sub={s.benchmark_cagr != null ? `benchmark ${pctSigned(s.benchmark_cagr)}` : undefined} />
        <MetricCard tone="sky" label="Total return" delay={60}
          value={pctSigned(s.total_return)} sub={`${res.period.years}y`} />
        <MetricCard tone="pink" label="Max drawdown" delay={120}
          value={<span className="text-loss">{pct(s.max_drawdown)}</span>}
          sub={s.max_dd_dates?.length ? `${s.max_dd_dates[0]} → ${s.max_dd_dates[1]}` : undefined} />
        <MetricCard tone="limeY" label="Sharpe" delay={180}
          value={num(s.sharpe)} sub={`Sortino ${num(s.sortino)}`} />
      </div>

      {/* mini metrics */}
      <div ref={ref} className="grid grid-cols-3 md:grid-cols-6 gap-3">
        <MetricMini label="Volatility" value={pct(s.volatility)} />
        <MetricMini label="Win rate" value={pct(s.win_rate)} />
        <MetricMini label="Profit factor" value={num(s.profit_factor)} />
        <MetricMini label="Turnover" value={<span className="text-warn">{pct(s.annual_turnover, 0)}</span>} />
        <MetricMini label="Active return" value={<span className={signClass(s.active_return)}>{s.active_return == null ? "—" : pctSigned(s.active_return)}</span>} />
        <MetricMini label="Exposure" value={pct(s.exposure, 0)} />
      </div>

      <CostStrip config={config} nTrades={s.n_trades} />

      {/* equity + drawdown */}
      <div className="grid lg:grid-cols-[1.55fr_1fr] gap-3.5">
        <Card className="p-5">
          <div className="flex items-center justify-between mb-1.5">
            <div className="font-extrabold text-[15px]">Equity curve</div>
            <div className="flex gap-3.5 text-[12px] font-semibold">
              <span className="flex items-center gap-1.5 text-ink"><span className="w-3.5 h-0.5 rounded bg-ink" />Strategy</span>
              {res.benchmark_curve?.length ? (
                <span className="flex items-center gap-1.5 text-faint"><span className="w-3.5 h-0.5 rounded" style={{ background: "#c3bdd0" }} />Benchmark</span>
              ) : null}
            </div>
          </div>
          <EquityChart strategy={res.equity_curve} benchmark={res.benchmark_curve} />
          <div className="text-[12px] text-faint mt-1.5">{moneyCompact(res.equity_curve[0]?.[1])} → {moneyCompact(res.equity_curve.slice(-1)[0]?.[1])}</div>
        </Card>
        <Card className="p-5">
          <div className="font-extrabold text-[15px] mb-1.5">Drawdown</div>
          <DrawdownChart curve={res.drawdown_curve} />
          <div className="text-[12px] text-faint mt-1.5">Deepest: <b className="text-loss">{pct(s.max_drawdown)}</b></div>
        </Card>
      </div>

      {/* engine notes — collapsed by default (the wall of data-provenance text the owner disliked) */}
      {res.warnings?.length > 0 && (
        <Card className="px-4 py-3">
          <button className="flex items-center gap-2 text-[13px] font-bold text-ink w-full text-left py-1.5" onClick={() => setShowNotes(!showNotes)}>
            <span className="inline-flex items-center justify-center w-5 h-5 rounded-md text-[13px] font-extrabold shrink-0" style={{ background: "#f1ecfb", color: "#5b4a9e" }}>{showNotes ? "−" : "+"}</span> Engine notes
            <span className="text-[11px] text-faint font-medium">— data provenance &amp; caveats ({res.warnings.length})</span>
          </button>
          {showNotes && (
            <ul className="text-[12px] text-muted space-y-1 list-disc pl-4 mt-2.5">
              {res.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          )}
        </Card>
      )}

      {/* trades */}
      <div>
        <div className="text-[13px] font-extrabold text-muted mb-2.5">Trades · {res.trades.length} total</div>
        <Card className="overflow-hidden">
          <div className="grid px-5 py-3 text-[11.5px] text-faint font-bold border-b" style={{ gridTemplateColumns: "1.1fr 1fr 1fr .8fr .6fr .6fr .9fr", borderColor: "#f0eef6" }}>
            <span>Ticker</span><span>Entry</span><span>Exit</span><span className="text-right">Return</span><span className="text-right">R</span><span className="text-right">Days</span><span className="text-right">Reason</span>
          </div>
          <div className="scroll-y" style={{ maxHeight: 380 }}>
            {res.trades.slice(0, 200).map((t, i) => (
              <div key={i} className="wf-row grid px-5 py-3 text-[13px] items-center tn border-b" style={{ gridTemplateColumns: "1.1fr 1fr 1fr .8fr .6fr .6fr .9fr", borderColor: "#f6f4fb" }}>
                <span className="font-bold">{t.ticker}</span>
                <span className="text-faint">{t.entry_date}</span>
                <span className="text-faint">{t.exit_date ?? "—"}</span>
                <span className={`text-right font-bold ${signClass(t.return_pct)}`}>{pctSigned(t.return_pct)}</span>
                <span className={`text-right ${signClass(t.r_multiple)}`}>{t.r_multiple == null ? "—" : num(t.r_multiple, 1)}</span>
                <span className="text-right text-faint">{t.holding_days}</span>
                <span className="text-right">
                  <span className="text-[11px] font-bold px-2 py-0.5 rounded-full" style={tonePill(EXIT_TONE[t.exit_reason] || "neutral")}>{t.exit_reason}</span>
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

function tonePill(tone: string): React.CSSProperties {
  const m: Record<string, [string, string]> = {
    good: ["#e6f4ea", "#1f7a4d"], bad: ["#fdeaf1", "#c23e74"], warn: ["#fff3da", "#9a6c12"], neutral: ["#eceaf2", "#7a7689"],
  };
  const [bg, color] = m[tone] || m.neutral;
  return { background: bg, color };
}

// labeled config grid — the single structured home for the run's definition (B-RES-CONFIG / C-6).
function ConfigGrid({ c, sv }: { c: StrategyConfig; sv: { survivorsOnly: boolean; offenders: string[] } }) {
  const row = (k: string, v: React.ReactNode) => (
    <div className="flex gap-2"><span className="text-faint w-[92px] shrink-0">{k}</span><span className="font-mono text-ink/80 break-words">{v}</span></div>
  );
  const screen = [...(c.universe?.filters ?? []), ...(c.entry_filters ?? [])];
  return (
    <div className="grid sm:grid-cols-2 gap-x-6 gap-y-1.5 text-[12px]">
      {row("Screener", screen.length ? screen.join("  ·  ") : "all names")}
      {row("Window", `${c.start} → ${c.end || "today"} · vs ${c.benchmark}`)}
      {row("Rank", rankDesc(c))}
      {row("Sizing", `top ${c.n_holdings} · ${c.weighting}${c.max_weight_per_stock ? ` · max ${Math.round(c.max_weight_per_stock * 100)}%/stock` : ""}${c.sector_cap ? ` · sector cap ${c.sector_cap}` : ""}`)}
      {row("Rebalance", c.rebalance)}
      {row("Costs", `NSE delivery · ~22 bps round-trip + ₹15.93 DP/sell · capital ₹${(c.capital / 1e5).toFixed(2)}L`)}
      {row("Exits", `stop ${c.stop_loss?.type ?? "none"} · tp ${c.take_profit?.type ?? "none"}${c.regime_filter?.enabled ? ` · regime MA${c.regime_filter.ma_period}` : ""}`)}
      {row("Universe", sv.survivorsOnly ? `survivors-only (${sv.offenders.join(", ")})` : "survivorship-free · point-in-time ₹500cr")}
    </div>
  );
}

// ── explore variations (parameter sweep) — moved here from the builder (iter-31): you tune AFTER
// you've seen a base result. Sweeps a small grid and ranks; "save" forks a new strategy + backtests it.
function setPath(obj: any, path: string[], val: any) {
  const o = { ...obj }; let cur = o;
  for (let i = 0; i < path.length - 1; i++) { cur[path[i]] = { ...cur[path[i]] }; cur = cur[path[i]]; }
  cur[path[path.length - 1]] = val; return o;
}
function applyOverrides(base: StrategyConfig, ov: Record<string, unknown>): StrategyConfig {
  let c: any = JSON.parse(JSON.stringify(base));
  for (const [path, val] of Object.entries(ov)) c = setPath(c, path.split("."), val);
  return c;
}

export function ExploreVariations({ config }: { config: StrategyConfig }) {
  const router = useRouter();
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
    if (!Object.keys(g).length) { setErr("Enter at least one comma-separated value to sweep."); setBusy(false); return; }
    try { setRes(await api.sweep({ ...config }, g, metric)); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }
  async function saveRow(overrides: Record<string, unknown>, rank: number) {
    const merged = applyOverrides(config, overrides);
    const sName = `${config.name || "strategy"}_v${rank}`;
    const sv = await api.saveStrategy(sName, merged);
    await api.runBacktest(merged, sv.id, true);
    router.push(`/strategies/${sv.id}`);
  }

  return (
    <div className="space-y-2.5">
      <div className="text-[12px] text-muted">Sweep a parameter grid &amp; rank to find a better setup. “Save” forks a new strategy and backtests it.</div>
      {["n_holdings", "stop_loss.mult", "rebalance"].map((p) => (
        <div key={p} className="flex items-center gap-2">
          <span className="text-[12px] font-mono text-muted" style={{ width: 110 }}>{p}</span>
          <input className="wf-in" placeholder="comma values e.g. 8, 10, 15" value={grid[p] || ""} onChange={(e) => setGrid({ ...grid, [p]: e.target.value })} />
        </div>
      ))}
      <div className="flex items-center gap-2">
        <select className="wf-in" style={{ width: 150 }} value={metric} onChange={(e) => setMetric(e.target.value)}>
          <option value="sharpe">rank by sharpe</option><option value="cagr">rank by CAGR</option><option value="sortino">rank by sortino</option>
        </select>
        <button className="btn btn-ink flex-1" style={{ borderRadius: 11 }} disabled={busy} onClick={runSweep}>{busy ? "running grid…" : "Run sweep"}</button>
      </div>
      {err && <div className="text-[12px] text-loss">{err}</div>}
      {res && (
        <div className="rounded-xl overflow-hidden bg-white border" style={{ borderColor: "#f0eef6" }}>
          <div className="grid px-3 py-2 text-[11px] text-faint font-bold border-b" style={{ gridTemplateColumns: "1.6fr .7fr .7fr .7fr .8fr", borderColor: "#f0eef6" }}>
            <span>Variant</span><span className="text-right">CAGR</span><span className="text-right">DD</span><span className="text-right">Sharpe</span><span></span>
          </div>
          <div className="scroll-y" style={{ maxHeight: 300 }}>
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
  );
}

// collapsible cost-sensitivity strip — re-runs the strategy at 0x/1x/2x costs on demand.
function CostStrip({ config, nTrades }: { config?: StrategyConfig; nTrades?: number }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<CostSensitivity | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const noTrades = nTrades === 0;

  async function load() {
    if (!config) return;
    setOpen(true);
    if (data || busy) return;
    setBusy(true); setErr(null);
    try { setData(await api.costSensitivity(config)); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <Card className="px-5 py-3">
      <button className="flex items-center gap-2 text-[13px] font-bold text-ink w-full text-left py-1.5" onClick={() => (open ? setOpen(false) : (noTrades ? setOpen(true) : load()))}>
        <span className="inline-flex items-center justify-center w-5 h-5 rounded-md text-[13px] font-extrabold shrink-0" style={{ background: "#f1ecfb", color: "#5b4a9e" }}>{open ? "−" : "+"}</span> Cost sensitivity
        <span className="text-[11.5px] text-faint font-medium">— how much do costs eat the edge?</span>
      </button>
      {open && (
        <div className="mt-3">
          {!noTrades && <div className="text-[11.5px] text-muted mb-2.5">Re-runs this strategy at <b>0×</b> (no costs), <b>1×</b> (your real NSE costs) and <b>2×</b> (stress). If it still beats the benchmark at 2×, fees aren't killing the edge.</div>}
          {noTrades && <div className="text-[12px] text-faint">This strategy made no trades, so there's nothing to stress-test. Loosen the screen or pick a sort variable, then re-run.</div>}
          {!noTrades && busy && <div className="text-[12px] text-faint">running 0× / 1× / 2× …</div>}
          {err && <div className="text-[12px] text-loss">{err}</div>}
          {data && (
            <div className="grid grid-cols-3 gap-3">
              {data.runs.map((r) => (
                <div key={r.cost_multiplier} className="rounded-xl px-4 py-3" style={{ background: r.cost_multiplier === 1 ? "#eef6dd" : "#f7f5fc" }}>
                  <div className="text-[11.5px] font-bold text-muted">{r.cost_multiplier === 0 ? "0× (frictionless)" : r.cost_multiplier === 1 ? "1× (your costs)" : `${r.cost_multiplier}× (stress)`}</div>
                  <div className="text-[20px] font-extrabold mt-1 tn">{pctSigned(r.summary.cagr ?? 0)}</div>
                  <div className="text-[11px] text-faint">Sharpe {num(r.summary.sharpe ?? 0)} · turn {pct(r.summary.annual_turnover ?? 0, 0)}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
